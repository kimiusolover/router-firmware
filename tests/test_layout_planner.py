"""Regression tests for the fail-closed storage layout planner."""

from __future__ import annotations

import json
import os
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLATFORM_ROOT = Path(os.environ.get("ROUTER_PLATFORM_ROOT", str(ROOT.parent / "router-platform"))).resolve()


class LayoutPlannerTests(unittest.TestCase):
    def test_discovery_capabilities_emit_only_a_blocked_proposal(self) -> None:
        output = ROOT / "build" / "ax23v-v1" / "storage-layout.plan.json"
        try:
            result = subprocess.run(
                ["python3", "scripts/pipeline.py", "plan-storage", "--device", "ax23v-v1"],
                cwd=ROOT,
                check=False,
                text=True,
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            plan = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(plan["status"], "proposed")
            self.assertFalse(plan["validation"]["flashable"])
            self.assertFalse(plan["validation"]["final_eligible"])
            self.assertIn("physical_media_unverified", plan["validation"]["blockers"])
            self.assertIn("mtd_boundaries_unverified", plan["validation"]["blockers"])
            self.assertIn("ram_budget_unverified", plan["validation"]["blockers"])
            self.assertIn("mtd_boundaries_unverified", plan["validation"]["blockers"])
            self.assertTrue(all(region["offset"] == "unset" for region in plan["regions"]))
            capabilities = (PLATFORM_ROOT / "devices" / "tplink" / "archer-ax23v-v1" / "storage-capabilities.yaml").read_text(encoding="utf-8")
            self.assertIn("status: observed", capabilities)
            self.assertIn("capacity_policy_input: forbidden", capabilities)
        finally:
            try:
                output.unlink(missing_ok=True)
            except OSError:
                pass
            try:
                output.parent.rmdir()
                output.parent.parent.rmdir()
            except OSError:
                pass
