"""Regression tests for fail-closed tiny package planning."""

from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TinyPlannerTests(unittest.TestCase):
    def test_unknown_capabilities_do_not_select_conditionals(self) -> None:
        output = ROOT / "build" / "ax23v-v1" / "tiny.plan.json"
        try:
            result = subprocess.run(["python3", "scripts/pipeline.py", "plan-tiny", "--device", "ax23v-v1"], cwd=ROOT, check=False, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            plan = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(plan["status"], "proposed")
            self.assertFalse(plan["image_authorized"])
            hostapd = next(profile for profile in plan["profiles"] if profile["package"] == "hostapd")
            self.assertNotIn("ieee80211ax", hostapd["selected"])
            self.assertIn("ieee80211ax", {item["feature"] for item in hostapd["unresolved_conditionals"]})
            systemd = next(profile for profile in plan["profiles"] if profile["package"] == "systemd")
            self.assertIn("systemd", systemd["binaries_allowlist"])
            self.assertIn("systemd-networkd.service", systemd["units_allowlist"])
        finally:
            output.unlink(missing_ok=True)
            try:
                output.parent.rmdir(); output.parent.parent.rmdir()
            except OSError:
                pass
