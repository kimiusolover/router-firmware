"""Verify preview account staging without building packages or touching host accounts."""
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('pipeline', ROOT / 'scripts/pipeline.py')
pipeline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pipeline)


class PreviewAccountsTests(unittest.TestCase):
    def test_preview_staging(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / 'rootfs'
            pipeline.stage_rootfs('x86_64-qemu-uefi-preview', dest)
            accounts = {line.split(':')[0]: line.split(':') for line in
                        (dest / 'etc/passwd').read_text().splitlines()}
            self.assertEqual(set(accounts), {'root', 'admin'})
            self.assertEqual(accounts['admin'][2:4], ['1000', '1000'])
            self.assertTrue((dest / 'etc/shadow').read_text().startswith('root:!:'))
            # Windows chmod cannot represent POSIX owner/group permissions.
            if os.name != 'nt':
                self.assertEqual((dest / 'etc/shadow').stat().st_mode & 0o777, 0o600)
                for name in ('sudoers', 'sudoers.d/admin'):
                    self.assertEqual((dest / 'etc' / name).stat().st_mode & 0o777, 0o440)
                self.assertEqual((dest / 'home/admin').stat().st_mode & 0o777, 0o700)
            self.assertEqual((dest / 'etc/sudoers.d/admin').read_text().splitlines()[-1],
                             'admin ALL=(ALL:ALL) ALL')
            unit = dest / 'etc/systemd/system/getty.target.wants/serial-getty@ttyS0.service'
            # Git may materialize symlinks as text on Windows checkouts.
            target = unit.read_text() if os.name == 'nt' and not unit.is_symlink() else str(unit.readlink())
            self.assertEqual(target, '/usr/lib/systemd/system/serial-getty@.service')

    def test_physical_overlay_has_no_preview_accounts(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / 'rootfs'
            pipeline.stage_rootfs('ax23v-v1', dest)
            self.assertFalse((dest / 'etc/shadow').exists())
            self.assertFalse((dest / 'etc/sudoers.d/admin').exists())
            self.assertFalse((dest / 'home/admin').exists())
