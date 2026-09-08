#!/usr/bin/env python3
"""Assemble the explicitly opt-in Arch binary bootstrap (never a source release).
Run under unshare -Ur. All writes are regular files below build/ and dist/.
"""
import argparse
import tempfile
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import uuid

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / 'build/qemu-bootstrap'
DEVICE = 'x86_64-qemu-uefi-preview'
EPOCH = 1788825600
LAYOUT = 'qemu-uefi-gpt-v1'
NS = uuid.UUID('a45490d2-7c56-4acd-9eab-8a5566fd0659')
def guid(name): return str(uuid.uuid5(NS, f'{DEVICE}:{LAYOUT}:{name}'))
def run(*args, **kw): return subprocess.run([str(a) for a in args], check=True, **kw)
def digest(path):
    with path.open('rb') as f: return hashlib.file_digest(f, 'sha256').hexdigest()
def write(root, path, text, mode=0o644):
    p = root / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    p.chmod(mode)
def link(root, path, target):
    p = root / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.unlink(missing_ok=True)
    p.symlink_to(target)

def main():
    if os.geteuid() != 0: raise SystemExit('Run under unshare -Ur; real root is not required')
    parser = argparse.ArgumentParser()
    parser.add_argument('--rebuild', action='store_true')
    args = parser.parse_args()
    existing = [WORK/name for name in ('rootfs', 'initramfs-tree', 'esp-tree') if (WORK/name).exists()]
    if existing:
        if not args.rebuild: raise SystemExit('Build trees exist; use --rebuild to preserve them and rebuild')
        backup = Path(tempfile.mkdtemp(prefix='previous-', dir=WORK))
        for path in existing: path.rename(backup/path.name)
    packages = json.loads((WORK/'packages.lock.json').read_text())
    dest = WORK/'rootfs'
    if dest.exists(): raise SystemExit('rootfs exists: preserve it or use a fresh build directory')
    dest.mkdir()
    for pkg in packages:
        archive = WORK/'cache'/pkg['filename']
        if digest(archive) != pkg['sha256']: raise SystemExit(f'Package hash mismatch: {archive}')
        run('gpgv', '--keyring', WORK/'archlinux.gpg', str(archive)+'.sig', archive,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if 'guest' in pkg['roles']:
            run('bsdtar', '-xpf', archive, '--no-same-owner', '-C', dest, '--exclude=.PKGINFO', '--exclude=.BUILDINFO', '--exclude=.MTREE', '--exclude=.INSTALL')
    # Preserve package system accounts; add only the preview administrator.
    overlay = ROOT/'overlays'/DEVICE
    for name in ('passwd', 'group', 'shadow'):
        original = (dest/'etc'/name).read_text().splitlines()
        additions = (overlay/'etc'/name).read_text().splitlines()
        users = {line.split(':')[0]: line for line in original}
        if 'admin' in users: raise SystemExit('admin collides with package account')
        if name in ('passwd', 'group') and any(line.split(':')[2] == '1000' for line in original):
            raise SystemExit('uid/gid 1000 already allocated')
        for line in additions: users[line.split(':')[0]] = line
        write(dest, 'etc/'+name, '\n'.join(users.values())+'\n', 0o600 if name == 'shadow' else 0o644)
    for p in sorted(overlay.rglob('*')):
        relative = p.relative_to(overlay)
        if str(relative) in ('etc/passwd', 'etc/group', 'etc/shadow') or p.is_dir(): continue
        target = dest/relative
        if p.is_symlink(): link(dest, relative, os.readlink(p))
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(p, target)
    for p in ('etc/sudoers', 'etc/sudoers.d/admin'): (dest/p).chmod(0o440)
    (dest/'home/admin').mkdir(parents=True, exist_ok=True)
    (dest/'home/admin').chmod(0o700)
    write(dest, 'etc/hostname', 'routeros\n')
    write(dest, 'etc/machine-id', '')
    write(dest, 'etc/fstab', f'PARTUUID={guid("root")} / ext4 defaults 0 1\n')
    write(dest, 'etc/motd', 'Router OS QEMU binary bootstrap\nPublic test account. Serial-only Milestone 0.\n')
    write(dest, 'etc/profile.d/preview.sh', "export PS1='routeros-admin$ '\n")
    link(dest, 'etc/systemd/system/default.target', '/usr/lib/systemd/system/multi-user.target')
    for unit in ('systemd-networkd.service', 'systemd-networkd.socket', 'systemd-resolved.service', 'sshd.service'):
        link(dest, 'etc/systemd/system/'+unit, '/dev/null')
    write(dest, 'usr/share/routeros/binary-packages.json', json.dumps(packages, indent=2)+'\n')
    # No package post-install hooks execute on the host. sysusers/tmpfiles run in guest.
    kernel_dir = next((dest/'usr/lib/modules').glob('*/vmlinuz')).parent
    kernel_version = kernel_dir.name
    run('depmod', '-b', dest, kernel_version)
    init = WORK/'initramfs-tree'; init.mkdir()
    for name in ('bin', 'dev', 'proc', 'sys', 'newroot', 'lib/modules'): (init/name).mkdir(parents=True, exist_ok=True)
    busybox = dest/'usr/lib/initcpio/busybox'
    shutil.copyfile(busybox, init/'bin/busybox'); (init/'bin/busybox').chmod(0o755)
    for name in ('libc.so.6', 'libcrypt.so.2', 'libblkid.so.1', 'libmount.so.1', 'libsystemd.so.0', 'libgcc_s.so.1', 'ld-linux-x86-64.so.2'):
        shutil.copyfile(dest/'usr/lib'/name, init/'lib'/name)
        (init/'lib'/name).chmod(0o755)
    link(init, 'lib64', 'lib')
    link(init, 'usr/lib', '../lib')
    shutil.copyfile(dest/'usr/bin/blkid', init/'bin/blkid')
    (init/'bin/blkid').chmod(0o755)
    for name in ('mount', 'switch_root'):
        shutil.copyfile(dest/'usr/bin'/name, init/'bin'/name)
        (init/'bin'/name).chmod(0o755)
    for app in ('sh','sleep','echo','cat','mkdir'):
        link(init, 'bin/'+app, 'busybox')
    # This pinned kernel must provide boot storage drivers built in.
    for module in ('virtio_pci','virtio_blk','ext4'):
        lines = subprocess.check_output(['modprobe', '-d', str(dest), '-S', kernel_version, '--show-depends', module], text=True)
        if lines.strip() != 'builtin '+module:
            raise SystemExit('Bootstrap requires built-in kernel driver: '+module)
    write(init, 'init', '''#!/bin/sh
mount -t devtmpfs devtmpfs /dev
mount -t proc proc /proc
mount -t sysfs sysfs /sys
n=0
while [ ! -b /dev/vda2 ] && [ "$n" -lt 30 ]; do sleep 1; n=$((n+1)); done
rootdev=$(/bin/blkid -t PARTUUID=ROOT_GUID -o device /dev/vda2)
[ "$rootdev" = /dev/vda2 ] || { echo ROOT_GUID_MISMATCH; exec sh; }
mount -t ext4 "$rootdev" /newroot || { echo ROOT_MOUNT_FAILED; exec sh; }
mount --move /dev /newroot/dev
mount --move /proc /newroot/proc
mount --move /sys /newroot/sys
exec switch_root /newroot /usr/lib/systemd/systemd
'''.replace('ROOT_GUID', guid('root')), 0o755)
    # Prototype init uses the fixed runner's /dev/vda2, documented in metadata.
    for tree in (dest, init):
        for p in tree.rglob('*'): os.utime(p, (EPOCH, EPOCH), follow_symlinks=False)
    names = b'\0'.join(str(p.relative_to(init)).encode() for p in sorted(init.rglob('*'))) + b'\0'
    with (WORK/'initramfs.cpio').open('wb') as out:
        run('cpio', '--null', '-o', '-H', 'newc', '--reproducible', '--owner=0:0', input=names, cwd=init, stdout=out)
    esp = WORK/'esp-tree'
    (esp/'EFI/BOOT').mkdir(parents=True)
    (esp/'loader/entries').mkdir(parents=True)
    shutil.copyfile(dest/'usr/lib/systemd/boot/efi/systemd-bootx64.efi', esp/'EFI/BOOT/BOOTX64.EFI')
    shutil.copyfile(kernel_dir/'vmlinuz', esp/'vmlinuz-linux')
    shutil.copyfile(WORK/'initramfs.cpio', esp/'initramfs.cpio')
    write(esp, 'loader/loader.conf', 'default routeros.conf\ntimeout 0\neditor no\n')
    cmdline = f'root=PARTUUID={guid("root")} rootfstype=ext4 rw console=ttyS0,115200n8 systemd.log_target=console'
    write(esp, 'loader/entries/routeros.conf', 'title Router OS QEMU bootstrap\nlinux /vmlinuz-linux\ninitrd /initramfs.cpio\noptions '+cmdline+'\n')
    if sum(p.stat().st_size for p in esp.rglob('*') if p.is_file()) > 60*1024**2:
        raise SystemExit('ESP content exceeds 60 MiB payload limit')
    tools = WORK/'tools/usr/bin'
    fat = WORK/'esp.fat'
    with fat.open('wb') as f: f.truncate(64*1024**2)
    run(tools/'mkfs.fat', '-F', '32', '-i', '524F5350', '-n', 'ROUTERESP', fat)
    for p in sorted(esp.rglob('*')):
        target = '::/'+str(p.relative_to(esp))
        if p.is_dir(): run(tools/'mmd', '-i', fat, target)
        else: run(tools/'mcopy', '-i', fat, p, target)
    ext = WORK/'root.ext4'
    with ext.open('wb') as f: f.truncate(958*1024**2)
    run('mkfs.ext4', '-F', '-U', guid('rootfs'), '-L', 'ROUTERROOT', '-E', 'lazy_itable_init=0,lazy_journal_init=0', '-d', dest, ext)
    run('debugfs', '-w', '-R', 'set_inode_field /home/admin uid 1000', ext)
    run('debugfs', '-w', '-R', 'set_inode_field /home/admin gid 1000', ext)
    output = ROOT/'dist/routeros-x86_64-uefi-preview.img'
    output.parent.mkdir(exist_ok=True)
    temp = WORK/'image.tmp'
    with temp.open('wb') as f: f.truncate(1024**3)
    run(tools/'sgdisk', '--clear', '--disk-guid='+guid('disk'), '--new=1:2048:133119', '--typecode=1:ef00', '--change-name=1:ROUTERESP', '--partition-guid=1:'+guid('esp'), '--new=2:133120:2095103', '--typecode=2:8300', '--change-name=2:router-root', '--partition-guid=2:'+guid('root'), temp)
    with temp.open('r+b') as f:
        for offset, part in ((1024**2,fat),(65*1024**2,ext)):
            f.seek(offset)
            with part.open('rb') as src: shutil.copyfileobj(src,f)
    table = subprocess.check_output([str(tools/'sgdisk'), '-p', str(temp)], text=True)
    (WORK/'gpt.txt').write_text(table)
    metadata = {'version':2, 'device':DEVICE, 'qemu_only':True, 'uefi':True,
        'image_sha256':digest(temp), 'image_bytes':temp.stat().st_size,
        'layout_id':LAYOUT, 'console':'ttyS0', 'provenance_kind':'arch-binary-bootstrap',
        'package_lock_sha256':digest(WORK/'packages.lock.json')}
    temp.replace(output)
    sidecar = WORK/'metadata.tmp'; sidecar.write_text(json.dumps(metadata, indent=2)+'\n')
    sidecar.replace(Path(str(output)+'.qemu.json'))
    (WORK/'assembly.json').write_text(json.dumps({'metadata':metadata,'kernel_version':kernel_version,'cmdline':cmdline,'init_root_device':'/dev/vda2','gpt':table,'esp_files':{str(p.relative_to(esp)):digest(p) for p in esp.rglob('*') if p.is_file()},'bit_reproducibility_verified':False},indent=2)+'\n')
    print(output)

if __name__ == '__main__': main()
