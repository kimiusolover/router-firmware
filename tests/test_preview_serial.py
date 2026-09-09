"""Real serial control sequences must not hide successful guest output."""
import importlib.util
import io
import os
from pathlib import Path
from types import SimpleNamespace
import unittest

spec = importlib.util.spec_from_file_location(
    'preview_boot_test', Path(__file__).resolve().parents[1] / 'scripts/preview/boot_test.py')
boot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(boot)


class SerialOutputTests(unittest.TestCase):
    def test_uid_with_shell_control_sequences_preserves_raw_evidence(self):
        for uid in (b'1000', b'0'):
            with self.subTest(uid=uid):
                read_fd, write_fd = os.pipe()
                raw = (b'id -u\r\n\x1b[?2004l\r\x1b]3008;type=command\x1b\\'
                       + uid + b'\r\n\x1b]3008;exit=success\x1b\\routeros-admin$ ')
                os.write(write_fd, raw)
                os.close(write_fd)
                with os.fdopen(read_fd, 'rb') as output:
                    log = io.BytesIO()
                    serial = boot.Serial(SimpleNamespace(stdout=output), log)
                    serial.expect(rb'\n\r*' + uid + rb'\r*\n', timeout=1)
                    serial.expect(rb'routeros-admin\$ ', timeout=1)
                    self.assertEqual(log.getvalue(), raw)
