"""Regression tests for the fail-closed firmware pipeline."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLATFORM_ROOT = Path(os.environ.get("ROUTER_PLATFORM_ROOT", str(ROOT.parent / "router-platform"))).resolve()

import sys
sys.path.insert(0, str(ROOT / "scripts"))
import pipeline


class PipelineTests(unittest.TestCase):
    def run_pipeline(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["python3", "scripts/pipeline.py", *args],
            cwd=ROOT,
            check=False,
            text=True,
            capture_output=True,
        )

    def test_discovery_metadata_is_valid(self) -> None:
        result = self.run_pipeline("verify", "--device", "ax23v-v1")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_unlocked_sources_cannot_be_fetched(self) -> None:
        result = self.run_pipeline("fetch", "--device", "ax23v-v1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("status: locked", result.stderr)

    def test_discovery_device_cannot_produce_an_image(self) -> None:
        # Image starts with fetch, so it must fail before touching dist/.
        result = self.run_pipeline("image", "--device", "ax23v-v1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("status: locked", result.stderr)

    def test_qemu_preview_runner_is_serial_only_with_two_e1000e_nics(self) -> None:
        runner = (ROOT / "scripts" / "pipeline.py").read_text(encoding="utf-8")
        self.assertIn('"-display", "none", "-serial", "stdio"', runner)
        self.assertEqual(runner.count('"user,model=e1000e"'), 2)
        self.assertNotIn('"user,model=virtio-net-pci"', runner)

    def test_ax23v1_source_closure(self) -> None:
        closure = pipeline.target_required_sources("ax23v-v1")
        expected = {
            "linux",
            "systemd",
            "hostapd",
            "nftables",
            "unbound",
            "kea",
            "jool",
            "router-packages",
        }
        self.assertEqual(closure, expected)

    def test_unrelated_pending_source_does_not_block_fetch(self) -> None:
        dummy_yaml = ROOT / "sources" / "dummy_unrelated.yaml"
        dummy_yaml.write_text(
            "name: dummy-unrelated\n"
            "status: pending-verification\n"
            "upstream: https://example.com/\n"
            "revision: unset\n"
            "sha256: unset\n"
            "archive: unset\n"
            "license: MIT\n",
            encoding="utf-8",
        )
        try:
            result = self.run_pipeline("fetch", "--device", "ax23v-v1")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("source must be status: locked", result.stderr)
            self.assertNotIn("dummy_unrelated.yaml", result.stderr)
        finally:
            dummy_yaml.unlink(missing_ok=True)

    def test_required_pending_source_blocks_fetch(self) -> None:
        result = self.run_pipeline("fetch", "--device", "ax23v-v1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("source must be status: locked", result.stderr)

    def test_invalid_sha256_in_required_locked_source_fails_fetch(self) -> None:
        orig_sources = {}
        required_sources = ["hostapd", "jool", "kea", "kernel", "nftables", "systemd", "unbound"]
        for src_name in required_sources:
            path = ROOT / "sources" / f"{src_name}.yaml"
            orig_sources[path] = path.read_text(encoding="utf-8")
            path.write_text(
                f"name: {src_name if src_name != 'kernel' else 'linux'}\n"
                "status: locked\n"
                "upstream: https://example.com/\n"
                "revision: 1\n"
                "sha256: 0000000000000000000000000000000000000000000000000000000000000000\n"
                "license: MIT\n"
                "archive: https://example.com/archive.tar.gz\n",
                encoding="utf-8",
            )

        rp_yaml = ROOT / "sources" / "router-packages.yaml"
        orig_sources[rp_yaml] = rp_yaml.read_text(encoding="utf-8")
        invalid = orig_sources[rp_yaml].replace(
            "sha256: a02deee821a1b899a5bf95c69e878a5e08b89c4933f2b5c1f2732dca1d6d67d1",
            "sha256: invalidsha256",
        )
        rp_yaml.write_text(invalid, encoding="utf-8")
        try:
            result = self.run_pipeline("fetch", "--device", "ax23v-v1")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("sha256 must be 64 lowercase hexadecimal characters", result.stderr)
        finally:
            for path, content in orig_sources.items():
                path.write_text(content, encoding="utf-8")

    def test_router_packages_revision(self) -> None:
        rp_yaml = ROOT / "sources" / "router-packages.yaml"
        content = rp_yaml.read_text(encoding="utf-8")
        self.assertIn("revision: 0ea91909f8166dca42c8de4ee0f064a167eb7019", content)

    def test_sample_image_is_deterministic_and_unflashable(self) -> None:
        artifact = ROOT / "dist" / "ax23v-v1.bin"
        manifest = ROOT / "dist" / "ax23v-v1.manifest.json"
        checksums = ROOT / "dist" / "SHA256SUMS"
        provenance = ROOT / "dist" / "provenance.json"
        sbom = ROOT / "dist" / "ax23v-v1.sbom.cdx.json"
        try:
            first = self.run_pipeline("sample-image", "--device", "ax23v-v1")
            self.assertEqual(first.returncode, 0, first.stderr)
            initial = artifact.read_bytes()
            second = self.run_pipeline("sample-image", "--device", "ax23v-v1")
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(initial, artifact.read_bytes())
            self.assertTrue(initial.startswith(b"ROUTER-FIRMWARE-UNFLASHABLE" + bytes([0])))
            attestation = self.run_pipeline("attest", "--device", "ax23v-v1")
            self.assertEqual(attestation.returncode, 0, attestation.stderr)
            manifest_data = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual(manifest_data["schema"], 2)
            self.assertFalse(manifest_data["flashable"])
            self.assertEqual(manifest_data["artifacts"][0]["format"], "router-firmware-unflashable-fixture")
            self.assertEqual(manifest_data["artifacts"][1]["format"], "cyclonedx-1.5-json")
            sbom_data = json.loads(sbom.read_text(encoding="utf-8"))
            self.assertEqual(sbom_data["bomFormat"], "CycloneDX")
            self.assertEqual(sbom_data["specVersion"], "1.5")
            self.assertEqual(sbom_data["metadata"]["properties"][1]["value"], "false")
            self.assertIn("ax23v-v1.bin", checksums.read_text(encoding="utf-8"))
            self.assertIn("ax23v-v1.sbom.cdx.json", checksums.read_text(encoding="utf-8"))
            statement = json.loads(provenance.read_text(encoding="utf-8"))
            self.assertEqual(statement["subject"][0]["name"], "ax23v-v1.bin")
            self.assertEqual(statement["subject"][0]["digest"]["sha256"], manifest_data["artifacts"][0]["sha256"])
            self.assertEqual(statement["predicate"]["verifier"]["repository"], "kimiusolover/routerctl")
            self.assertEqual(statement["predicate"]["generator"], "router-firmware pipeline attest")
            self.assertTrue(statement["predicate"]["human_review"]["required"])
            self.assertIsNone(statement["predicate"]["human_review"]["reviewed_by"])
        finally:
            artifact.unlink(missing_ok=True)
            manifest.unlink(missing_ok=True)
            checksums.unlink(missing_ok=True)
            provenance.unlink(missing_ok=True)
            sbom.unlink(missing_ok=True)

    # Generic storage contract tests (Tests A-H)

    def get_canonical_ax23v1_contract_paths(self, tmpdir: str) -> tuple[Path, Path]:
        dir_path = Path(tmpdir)
        def_path = dir_path / "device.yaml"
        part_path = dir_path / "partitions.yaml"

        def_path.write_text(
            "schema: router-platform.device/v1\n"
            "id: ax23v-v1\n"
            "status: discovery\n"
            "preserve:\n"
            "  - u-boot\n"
            "  - config\n"
            "  - tplink\n"
            "  - radio\n",
            encoding="utf-8",
        )
        part_path.write_text(
            "schema: router-platform.partitions/v1\n"
            "status: discovery\n"
            "media:\n"
            "  type: spi-nor\n"
            "  total_bytes: 16777216\n"
            "preserve:\n"
            "  - u-boot\n"
            "  - config\n"
            "  - tplink\n"
            "  - radio\n"
            "replaceable:\n"
            "  - firmware\n"
            "partitions:\n"
            "  - name: u-boot\n"
            "    offset: 0x000000\n"
            "    size: 0x040000\n"
            "    preservation: preserve\n"
            "  - name: firmware\n"
            "    offset: 0x040000\n"
            "    size: 0xf60000\n"
            "    preservation: replaceable\n"
            "  - name: config\n"
            "    offset: 0xfa0000\n"
            "    size: 0x010000\n"
            "    preservation: preserve\n"
            "  - name: tplink\n"
            "    offset: 0xfb0000\n"
            "    size: 0x040000\n"
            "    preservation: preserve\n"
            "  - name: radio\n"
            "    offset: 0xff0000\n"
            "    size: 0x010000\n"
            "    preservation: preserve\n",
            encoding="utf-8",
        )
        return def_path, part_path

    def test_a_ax23v1_canonical_preservation_contract_passes(self) -> None:
        """Test A — AX23 v1 canonical preservation passes validation."""
        _, def_path, part_path = pipeline.device_paths("ax23v-v1")
        if not pipeline.parse_partitions_yaml(part_path).get("partitions"):
            with tempfile.TemporaryDirectory() as tmpdir:
                def_path, part_path = self.get_canonical_ax23v1_contract_paths(tmpdir)
                contract = pipeline.validate_storage_contract(part_path, def_path)
                self.assertEqual(contract["status"], "discovery")
                p_names = [p["name"] for p in contract["partitions"] if p.get("preservation") == "preserve"]
                self.assertEqual(p_names, ["u-boot", "config", "tplink", "radio"])
        else:
            contract = pipeline.validate_storage_contract(part_path, def_path)
            self.assertEqual(contract["status"], "discovery")
            preserved = pipeline.get_preserved_partitions("ax23v-v1")
            self.assertEqual(preserved, ["u-boot", "config", "tplink", "radio"])

    def test_b_factory_art_uboot_env_absence_passes(self) -> None:
        """Test B — Absence of factory/art/u-boot-env in contract passes."""
        _, def_path, part_path = pipeline.device_paths("ax23v-v1")
        if not pipeline.parse_partitions_yaml(part_path).get("partitions"):
            with tempfile.TemporaryDirectory() as tmpdir:
                def_path, part_path = self.get_canonical_ax23v1_contract_paths(tmpdir)
                contract = pipeline.validate_storage_contract(part_path, def_path)
                p_names = [p["name"] for p in contract["partitions"] if p.get("preservation") == "preserve"]
                self.assertNotIn("factory", p_names)
                self.assertNotIn("art", p_names)
                self.assertNotIn("u-boot-env", p_names)
        else:
            preserved = pipeline.get_preserved_partitions("ax23v-v1")
            self.assertNotIn("factory", preserved)
            self.assertNotIn("art", preserved)
            self.assertNotIn("u-boot-env", preserved)

    def test_c_custom_fake_board_contract_passes(self) -> None:
        """Test C — Generic storage contract validation accepts custom fake board layout."""
        with tempfile.TemporaryDirectory() as tmpdir:
            dir_path = Path(tmpdir)
            def_path = dir_path / "device.yaml"
            part_path = dir_path / "partitions.yaml"

            def_path.write_text("id: fake-board\nstatus: discovery\npreserve:\n  - boot\n  - env\n  - calibration\n", encoding="utf-8")
            part_path.write_text(
                "status: discovery\n"
                "media:\n"
                "  total_bytes: 16777216\n"
                "preserve:\n"
                "  - boot\n"
                "  - env\n"
                "  - calibration\n"
                "replaceable:\n"
                "  - firmware\n"
                "partitions:\n"
                "  - name: boot\n"
                "    offset: 0x000000\n"
                "    size: 0x040000\n"
                "    preservation: preserve\n"
                "  - name: env\n"
                "    offset: 0x040000\n"
                "    size: 0x010000\n"
                "    preservation: preserve\n"
                "  - name: firmware\n"
                "    offset: 0x050000\n"
                "    size: 0xf00000\n"
                "    preservation: replaceable\n"
                "  - name: calibration\n"
                "    offset: 0xf50000\n"
                "    size: 0x010000\n"
                "    preservation: preserve\n",
                encoding="utf-8",
            )
            parsed = pipeline.validate_storage_contract(part_path, def_path)
            self.assertEqual(parsed["status"], "discovery")
            p_names = [p["name"] for p in parsed["partitions"] if p.get("preservation") == "preserve"]
            self.assertEqual(p_names, ["boot", "env", "calibration"])

    def test_d_missing_or_null_preservation_classification_rejected(self) -> None:
        """Test D — Rejects partition missing or null preservation classification."""
        with tempfile.TemporaryDirectory() as tmpdir:
            dir_path = Path(tmpdir)
            def_path = dir_path / "device.yaml"
            part_path = dir_path / "partitions.yaml"

            def_path.write_text("id: test-board\nstatus: discovery\n", encoding="utf-8")
            part_path.write_text(
                "status: discovery\n"
                "partitions:\n"
                "  - name: boot\n"
                "    offset: 0x000000\n"
                "    size: 0x040000\n"
                "    preservation: null\n",
                encoding="utf-8",
            )
            with self.assertRaises(RuntimeError) as ctx:
                pipeline.validate_storage_contract(part_path, def_path)
            self.assertIn("invalid preservation status", str(ctx.exception))

    def test_e_unknown_preservation_classification_rejected(self) -> None:
        """Test E — Rejects unknown preservation classification like maybe."""
        with tempfile.TemporaryDirectory() as tmpdir:
            dir_path = Path(tmpdir)
            def_path = dir_path / "device.yaml"
            part_path = dir_path / "partitions.yaml"

            def_path.write_text("id: test-board\nstatus: discovery\n", encoding="utf-8")
            part_path.write_text(
                "status: discovery\n"
                "partitions:\n"
                "  - name: boot\n"
                "    offset: 0x000000\n"
                "    size: 0x040000\n"
                "    preservation: maybe\n",
                encoding="utf-8",
            )
            with self.assertRaises(RuntimeError) as ctx:
                pipeline.validate_storage_contract(part_path, def_path)
            self.assertIn("invalid preservation status", str(ctx.exception))

    def test_f_overlapping_partitions_rejected(self) -> None:
        """Test F — Rejects overlapping partitions."""
        with tempfile.TemporaryDirectory() as tmpdir:
            dir_path = Path(tmpdir)
            def_path = dir_path / "device.yaml"
            part_path = dir_path / "partitions.yaml"

            def_path.write_text("id: test-board\nstatus: discovery\n", encoding="utf-8")
            part_path.write_text(
                "status: discovery\n"
                "partitions:\n"
                "  - name: p1\n"
                "    offset: 0x000000\n"
                "    size: 0x040000\n"
                "    preservation: preserve\n"
                "  - name: p2\n"
                "    offset: 0x020000\n"
                "    size: 0x040000\n"
                "    preservation: replaceable\n",
                encoding="utf-8",
            )
            with self.assertRaises(RuntimeError) as ctx:
                pipeline.validate_storage_contract(part_path, def_path)
            self.assertIn("partitions overlap", str(ctx.exception))

    def test_g_exceeding_media_bounds_rejected(self) -> None:
        """Test G — Rejects partition exceeding media bounds."""
        with tempfile.TemporaryDirectory() as tmpdir:
            dir_path = Path(tmpdir)
            def_path = dir_path / "device.yaml"
            part_path = dir_path / "partitions.yaml"

            def_path.write_text("id: test-board\nstatus: discovery\n", encoding="utf-8")
            part_path.write_text(
                "status: discovery\n"
                "media:\n"
                "  total_bytes: 0x10000\n"
                "partitions:\n"
                "  - name: p1\n"
                "    offset: 0x000000\n"
                "    size: 0x20000\n"
                "    preservation: preserve\n",
                encoding="utf-8",
            )
            with self.assertRaises(RuntimeError) as ctx:
                pipeline.validate_storage_contract(part_path, def_path)
            self.assertIn("exceed media size", str(ctx.exception))

    def test_h_overwrite_preserved_region_rejected(self) -> None:
        """Test H — Rejects operations attempting to overwrite preserved partitions/regions."""
        with self.assertRaises(RuntimeError) as ctx1:
            pipeline.validate_image_target_region("ax23v-v1", "u-boot")
        self.assertIn("refusing to overwrite preserved partition", str(ctx1.exception))

        with self.assertRaises(RuntimeError) as ctx2:
            pipeline.validate_image_target_region("ax23v-v1", (0x000000, 0x020000))
        self.assertIn("refusing to overwrite preserved region", str(ctx2.exception))

        # Target replaceable partition should pass without exception
        pipeline.validate_image_target_region("ax23v-v1", "firmware")
