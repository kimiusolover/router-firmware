#!/usr/bin/env python3
"""Interactive serial-only binary-bootstrap launcher; explicit --execute required."""
import argparse
import os
from pathlib import Path
import shlex
import subprocess
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from preview_vm import validate_image, fresh_storage
ROOT=Path(__file__).resolve().parents[2]
def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--execute',action='store_true'); args=parser.parse_args()
    tools=ROOT/'build/qemu-bootstrap/tools/usr'
    image,meta=validate_image(ROOT,'routeros-x86_64-uefi-preview.img')
    env=os.environ.copy(); env['LD_LIBRARY_PATH']=str(tools/'lib'); env['QEMU_MODULE_DIR']=str(tools/'lib/qemu')
    os.environ['LD_LIBRARY_PATH']=env['LD_LIBRARY_PATH']
    session,overlay=fresh_storage(ROOT,image,meta,tools/'bin/qemu-img',tools/'share/edk2/x64/OVMF_CODE.4m.fd',tools/'share/edk2/x64/OVMF_VARS.4m.fd')
    command=[str(tools/'bin/qemu-system-x86_64'),'-L',str(tools/'share/qemu'),'-machine','q35','-accel','tcg','-cpu','max','-m','1024',
        '-display','none','-serial','stdio','-monitor','none','-nic','none',
        '-drive',f'if=pflash,format=raw,readonly=on,file={session}/OVMF_CODE.fd',
        '-drive',f'if=pflash,format=raw,file={session}/OVMF_VARS.fd',
        '-drive',f'if=virtio,format=qcow2,file={overlay}']
    if args.execute: subprocess.run(command,env=env,check=True)
    else: print('Prepared only; use --execute to start.\n'+shlex.join(command))
if __name__=='__main__': main()
