"""Validated QEMU image and fresh per-run storage shared by both launchers."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

DEVICE = 'x86_64-qemu-uefi-preview'

def sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

def validate_image(root, image_name):
    image = root/'dist'/image_name
    sidecar = root/'dist'/(image_name+'.qemu.json')
    for p in (image, sidecar):
        if not p.is_file() or p.is_symlink() or p.resolve().parent != (root/'dist').resolve():
            raise ValueError('Image and metadata must be regular files directly in dist/')
    data = json.loads(sidecar.read_text())
    expected = {'version','device','qemu_only','uefi','image_sha256','image_bytes',
                'layout_id','console','provenance_kind','package_lock_sha256'}
    if set(data) != expected or type(data['version']) is not int or data['version'] != 2:
        raise ValueError('QEMU metadata v2 with exact schema is required')
    if data['device'] != DEVICE or data['qemu_only'] is not True or data['uefi'] is not True:
        raise ValueError('QEMU-only UEFI constraints required')
    if data['console'] != 'ttyS0' or data['layout_id'] != 'qemu-uefi-gpt-v1':
        raise ValueError('Unknown layout or console')
    if data['provenance_kind'] != 'arch-binary-bootstrap':
        raise ValueError('Unknown bootstrap provenance')
    for key in ('image_sha256','package_lock_sha256'):
        value = data[key]
        if not isinstance(value, str) or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
            raise ValueError('Invalid digest: '+key)
    if type(data['image_bytes']) is not int or data['image_bytes'] != image.stat().st_size:
        raise ValueError('Image size mismatch')
    if data['image_sha256'] != sha256(image):
        raise ValueError('Image SHA-256 mismatch')
    return image, data

def fresh_storage(root, image, data, qemu_img, code, vars_template):
    for path in (code, vars_template):
        if not path.is_file(): raise ValueError('Readable OVMF CODE and VARS template required')
        if ',' in str(path): raise ValueError('Comma in firmware path is not supported')
    parent = root/'build'/DEVICE/'qemu'
    parent.mkdir(parents=True, exist_ok=True)
    if not parent.resolve().is_relative_to((root/'build').resolve()):
        raise ValueError('QEMU run directory must remain inside build/')
    session = Path(tempfile.mkdtemp(prefix=data['image_sha256'][:16]+'-', dir=parent))
    # A private base copy also prevents another build from changing this run's backing data.
    base = session/'base.img'
    if sys.platform.startswith('linux'):
        subprocess.run(['cp','--reflink=auto','--',str(image),str(base)],check=True)
    else:
        shutil.copyfile(image, base)
    if sha256(base) != data['image_sha256']: raise ValueError('Base image changed during preparation')
    base.chmod(0o444)
    overlay = session/'disk.qcow2'
    subprocess.run([str(qemu_img),'create','-f','qcow2','-F','raw','-b',str(base),str(overlay)],check=True)
    shutil.copyfile(code,session/'OVMF_CODE.fd')
    (session/'OVMF_CODE.fd').chmod(0o444)
    shutil.copyfile(vars_template,session/'OVMF_VARS.fd')
    return session, overlay
