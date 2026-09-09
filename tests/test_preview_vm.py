"""Regression coverage for stale-base and metadata acceptance boundaries."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('preview_vm',ROOT/'scripts/preview_vm.py')
vm=importlib.util.module_from_spec(spec); spec.loader.exec_module(vm)

class PreviewVMTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name); (self.root/'dist').mkdir()
        self.image=self.root/'dist/test.img'; self.image.write_bytes(b'current base')
        self.metadata={'version':2,'device':vm.DEVICE,'qemu_only':True,'uefi':True,
            'image_sha256':vm.sha256(self.image),'image_bytes':self.image.stat().st_size,
            'layout_id':'qemu-uefi-gpt-v1','console':'ttyS0','provenance_kind':'arch-binary-bootstrap',
            'package_lock_sha256':'a'*64}
        self.sidecar=self.root/'dist/test.img.qemu.json'; self.save()
    def save(self): self.sidecar.write_text(json.dumps(self.metadata))
    def test_current_image_accepted(self):
        self.assertEqual(vm.validate_image(self.root,'test.img')[1],self.metadata)
    def test_same_size_modified_image_rejected(self):
        self.image.write_bytes(b'changed base')
        with self.assertRaisesRegex(ValueError,'SHA-256'): vm.validate_image(self.root,'test.img')
    def test_truncated_image_rejected(self):
        self.image.write_bytes(b'x')
        with self.assertRaisesRegex(ValueError,'size mismatch'): vm.validate_image(self.root,'test.img')
    def test_legacy_metadata_rejected(self):
        self.metadata={'device':vm.DEVICE,'qemu_only':True,'uefi':True,'version':1}; self.save()
        with self.assertRaises(ValueError): vm.validate_image(self.root,'test.img')
    def test_symlink_image_rejected(self):
        original=self.root/'old.img'; self.image.rename(original); self.image.symlink_to(original)
        with self.assertRaises(ValueError): vm.validate_image(self.root,'test.img')
    def test_non_boolean_constraint_rejected(self):
        self.metadata['qemu_only']=1; self.save()
        with self.assertRaises(ValueError): vm.validate_image(self.root,'test.img')
    def test_new_run_has_new_overlay_and_private_base(self):
        code=self.root/'code'; code.write_bytes(b'code')
        vars_template=self.root/'vars'; vars_template.write_bytes(b'vars')
        original_run=vm.subprocess.run
        def execute(command, **kwargs):
            if command[0]=='test-qemu-img': Path(command[-1]).write_bytes(b'overlay')
            else: return original_run(command,**kwargs)
        with patch.object(vm.subprocess,'run',side_effect=execute):
            first,overlay1=vm.fresh_storage(self.root,self.image,self.metadata,'test-qemu-img',code,vars_template)
            second,overlay2=vm.fresh_storage(self.root,self.image,self.metadata,'test-qemu-img',code,vars_template)
        self.assertNotEqual(overlay1,overlay2)
        self.image.write_bytes(b'changed base')
        self.assertEqual((first/'base.img').read_bytes(),b'current base')
        (first/'OVMF_VARS.fd').write_bytes(b'guest mutation')
        self.assertEqual(vars_template.read_bytes(),b'vars')
        self.assertEqual((second/'OVMF_VARS.fd').read_bytes(),b'vars')
