#!/usr/bin/env python3
"""Retrieve pinned signed packages into build/, without host installation.
Offline by default; --fetch permits HTTPS downloads for missing cache entries.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import urllib.parse
ROOT=Path(__file__).resolve().parents[2]
WORK=ROOT/'build/qemu-bootstrap'
def digest(p):
    with p.open('rb') as f: return hashlib.file_digest(f,'sha256').hexdigest()
def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--fetch',action='store_true'); args=parser.parse_args()
    WORK.mkdir(parents=True,exist_ok=True); (WORK/'cache').mkdir(exist_ok=True)
    lock=Path(__file__).with_name('packages.lock.json')
    packages=json.loads(lock.read_text())
    subprocess.run(['gpg','--batch','--yes','--dearmor','--output',str(WORK/'archlinux.gpg'),'/usr/share/pacman/keyrings/archlinux.gpg'],check=True)
    for p in packages:
        name=p['filename']
        if Path(name).name != name or urllib.parse.urlparse(p['url']).scheme != 'https': raise ValueError('Invalid package lock')
        archive=WORK/'cache'/name
        for suffix in ('','.sig'):
            target=Path(str(archive)+suffix)
            if target.is_file(): continue
            cached=Path('/var/cache/pacman/pkg')/(name+suffix)
            if cached.is_file(): shutil.copyfile(cached,target)
            elif args.fetch:
                tmp=Path(str(target)+'.part')
                subprocess.run(['curl','--proto','=https','--proto-redir','=https','--fail','--location','--retry','2',p['url']+suffix,'-o',str(tmp)],check=True)
                tmp.replace(target)
            else: raise SystemExit('Missing cached package/signature; rerun with --fetch: '+str(target))
        if digest(archive)!=p['sha256']: raise ValueError('Package SHA-256 mismatch: '+name)
        status=subprocess.check_output(['gpgv','--status-fd','1','--keyring',str(WORK/'archlinux.gpg'),str(archive)+'.sig',str(archive)],text=True)
        if not any(l.startswith('[GNUPG:] VALIDSIG '+p['signer_fingerprint']+' ') for l in status.splitlines()):
            raise ValueError('Signer mismatch: '+name)
    # Emit lock only after every input has passed validation.
    shutil.copyfile(lock,WORK/'packages.lock.json')
    tools=WORK/'tools'; tools.mkdir(exist_ok=True)
    for p in packages:
        if 'host' in p['roles']:
            subprocess.run(['bsdtar','-xf',str(WORK/'cache'/p['filename']),'-C',str(tools),'--exclude=.PKGINFO','--exclude=.MTREE','--exclude=.BUILDINFO','--exclude=.INSTALL'],check=True)
    print('Pinned package cache verified; tools extracted under '+str(tools))
if __name__=='__main__': main()
