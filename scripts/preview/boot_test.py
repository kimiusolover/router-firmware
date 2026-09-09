#!/usr/bin/env python3
"""Cold boot and authenticate over serial; never execute guest commands on host."""
import argparse
import json
import os
from pathlib import Path
import re
import queue
import threading
import subprocess
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from preview_vm import validate_image, fresh_storage, sha256
ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT/'build/qemu-bootstrap'

class Serial:
    def __init__(self, proc, logfile):
        self.proc, self.logfile, self.buffer = proc, logfile, b''
        self.chunks = queue.Queue()
        # Windows select() accepts sockets only, not subprocess pipes.
        threading.Thread(target=self._read_output, daemon=True).start()

    def _read_output(self):
        try:
            while True:
                data = os.read(self.proc.stdout.fileno(), 65536)
                self.chunks.put(data)
                if not data:
                    return
        except OSError as error:
            self.chunks.put(error)
    def send(self, text): self.proc.stdin.write((text+'\n').encode()); self.proc.stdin.flush()
    def expect(self, pattern, timeout=60):
        end = time.monotonic()+timeout
        while time.monotonic() < end:
            # Keep raw transcript; strip terminal control sequences only for matching.
            self.buffer = re.sub(rb'\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)', b'', self.buffer)
            self.buffer = re.sub(rb'\x1bP.*?\x1b\\', b'', self.buffer, flags=re.S)
            self.buffer = re.sub(rb'\x1b\[[0-?]*[ -/]*[@-~]', b'', self.buffer)
            if b'Kernel panic' in self.buffer or b'ROOT_MOUNT_FAILED' in self.buffer or b'ROOT_GUID_MISMATCH' in self.buffer:
                raise RuntimeError('Guest boot failed; inspect serial transcript')
            match = re.search(pattern, self.buffer)
            if match:
                self.buffer = self.buffer[match.end():]
                return match
            try:
                data = self.chunks.get(timeout=max(0, end-time.monotonic()))
            except queue.Empty:
                break
            if isinstance(data, OSError):
                raise RuntimeError('Cannot read QEMU serial output') from data
            if not data: raise RuntimeError('QEMU exited before expected serial output: '+repr(pattern))
            self.logfile.write(data); self.logfile.flush(); self.buffer += data
        raise TimeoutError('Expected serial output not seen: '+repr(pattern))

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--negative-loader', action='store_true')
    parser.add_argument('--execute', action='store_true', required=True)
    args=parser.parse_args()
    image, metadata=validate_image(ROOT, 'routeros-x86_64-uefi-preview.img')
    if sha256(WORK/'packages.lock.json') != metadata['package_lock_sha256']:
        raise ValueError('Package evidence does not match image')
    tools=WORK/'tools/usr'
    env=os.environ.copy()
    env['LD_LIBRARY_PATH']=str(tools/'lib')
    env['QEMU_MODULE_DIR']=str(tools/'lib/qemu')
    # qemu-img needs the same private shared library search path.
    os.environ['LD_LIBRARY_PATH']=env['LD_LIBRARY_PATH']
    code=tools/'share/edk2/x64/OVMF_CODE.4m.fd'; vars_template=tools/'share/edk2/x64/OVMF_VARS.4m.fd'
    if args.negative_loader:
        damaged=WORK/'missing-loader.img'
        subprocess.run(['cp','--reflink=auto','--',str(image),str(damaged)],check=True)
        subprocess.run([str(tools/'bin/mdel'),'-i',str(damaged)+'@@1048576','::/EFI/BOOT/BOOTX64.EFI'],check=True)
        image=damaged
        metadata=dict(metadata, image_sha256=sha256(image))
    session, overlay=fresh_storage(ROOT,image,metadata,tools/'bin/qemu-img',code,vars_template)
    command=[str(tools/'bin/qemu-system-x86_64'),'-L',str(tools/'share/qemu'),
        '-machine','q35','-accel','tcg','-cpu','max','-m','1024','-display','none',
        '-serial','stdio','-monitor','none','-no-reboot','-nic','none',
        '-drive',f'if=pflash,format=raw,readonly=on,file={session}/OVMF_CODE.fd',
        '-drive',f'if=pflash,format=raw,file={session}/OVMF_VARS.fd',
        '-drive',f'if=virtio,format=qcow2,file={overlay}']
    evidence={'schema':1,'result':'failed','negative_loader':args.negative_loader,
        'image':metadata,'command':command,'ovmf_code_sha256':sha256(session/'OVMF_CODE.fd'),
        'ovmf_vars_template_sha256':sha256(vars_template),
        'qemu_version':subprocess.check_output([command[0],'--version'],env=env,text=True),
        'source_lock_commit':None,'provenance_kind':'arch-binary-bootstrap',
        'firmware_checkout':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'checks':[]}
    transcript=session/'serial.log'
    proc=None
    try:
        with transcript.open('wb') as log:
            proc=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,env=env)
            serial=Serial(proc,log)
            if args.negative_loader:
                serial.expect(rb'(failed to load|No bootable|UEFI Interactive Shell)',180)
                try:
                    serial.expect(rb'routeros login:',45)
                except TimeoutError:
                    evidence['checks'].append('missing_loader_does_not_reach_login')
                else: raise RuntimeError('Missing loader incorrectly reached login')
            else:
                serial.expect(rb'routeros login:',240); evidence['checks'].append('cold_boot_login_prompt')
                serial.send('admin'); serial.expect(rb'Password:'); serial.send('preview-admin')
                serial.expect(rb'routeros-admin\$ ')
                serial.send('id -u'); serial.expect(rb'\n\r*1000\r*\n'); serial.expect(rb'routeros-admin\$ ')
                evidence['checks'].append('admin_password_login_uid_1000')
                serial.send("sudo -k; sudo -S -p 'SUDO-PASSWORD: ' id -u")
                # One rejection exercises authentication without triggering the
                # upstream PAM lockout after three consecutive failures.
                serial.expect(rb'id -u\r?\n'); serial.expect(rb'SUDO-PASSWORD: ')
                serial.send('incorrect-preview-password')
                serial.expect(rb'Sorry, try again.'); serial.expect(rb'SUDO-PASSWORD: ')
                evidence['checks'].append('sudo_wrong_password_rejected')
                serial.send('preview-admin')
                serial.expect(rb'\n\r*0\r*\n'); serial.expect(rb'routeros-admin\$ ')
                evidence['checks'].append('sudo_correct_password_uid_0')
                serial.send('sudo visudo -cf /etc/sudoers')
                serial.expect(rb'/etc/sudoers: parsed OK'); serial.expect(rb'/etc/sudoers.d/admin: parsed OK'); serial.expect(rb'routeros-admin\$ ')
                evidence['checks'].append('target_sudoers_valid')
                serial.send('exit'); serial.expect(rb'routeros login:')
                serial.send('root'); serial.expect(rb'Password:'); serial.send('preview-admin')
                serial.expect(rb'Login incorrect'); evidence['checks'].append('root_password_login_rejected')
                serial.expect(rb'routeros login:'); serial.send('admin'); serial.expect(rb'Password:'); serial.send('preview-admin'); serial.expect(rb'routeros-admin\$ ')
                serial.send("sudo -k; sudo -S -p 'SUDO-PASSWORD: ' systemctl poweroff")
                serial.expect(rb'systemctl poweroff\r?\n'); serial.expect(rb'SUDO-PASSWORD: '); serial.send('preview-admin')
                proc.wait(timeout=90)
                if proc.returncode != 0: raise RuntimeError('QEMU exited unsuccessfully')
                evidence['checks'].append('guest_poweroff')
            evidence['result']='passed'
    except Exception as error:
        evidence['error']=str(error)
        raise
    finally:
        if proc and proc.poll() is None:
            proc.terminate()
            try: proc.wait(timeout=10)
            except subprocess.TimeoutExpired: proc.kill(); proc.wait()
        evidence['serial_sha256']=sha256(transcript)
        evidence['base_unchanged']=sha256(session/'base.img') == metadata['image_sha256']
        if not evidence['base_unchanged']: evidence['result']='failed'
        (session/'evidence.json').write_text(json.dumps(evidence,indent=2)+'\n')
        print(session/'evidence.json',flush=True)
    if evidence['result'] != 'passed': raise SystemExit(1)
if __name__ == '__main__': main()
