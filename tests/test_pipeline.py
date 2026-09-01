"""Regression tests for the fail-closed firmware pipeline."""

from __future__ import annotations

import subprocess
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


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

    def test_qemu_preview_metadata_is_valid_but_image_assembly_is_blocked(self) -> None:
        verified = self.run_pipeline("verify", "--device", "x86_64-qemu-uefi-preview")
        self.assertEqual(verified.returncode, 0, verified.stderr)
        image = self.run_pipeline("image", "--device", "x86_64-qemu-uefi-preview")
        self.assertNotEqual(image.returncode, 0)
        self.assertIn("status: locked", image.stderr)

    def test_qemu_runner_requires_a_verified_preview_artifact(self) -> None:
        result = self.run_pipeline("run-qemu", "--device", "x86_64-qemu-uefi-preview")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("QEMU preview image", result.stderr)

    def test_qemu_runner_rejects_a_symlinked_preview_artifact(self) -> None:
        dist = ROOT / "dist"
        dist.mkdir(exist_ok=True)
        image = dist / "routeros-x86_64-uefi-preview.img"
        metadata = dist / "routeros-x86_64-uefi-preview.img.qemu.json"
        target = dist / "not-a-preview.img"
        try:
            target.write_bytes(b"not a preview")
            image.symlink_to(target.name)
            metadata.write_text('{"device":"x86_64-qemu-uefi-preview","qemu_only":true,"uefi":true,"version":1}', encoding="utf-8")
            result = self.run_pipeline("run-qemu", "--device", "x86_64-qemu-uefi-preview")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("QEMU preview image", result.stderr)
        finally:
            image.unlink(missing_ok=True)
            metadata.unlink(missing_ok=True)
            target.unlink(missing_ok=True)

    def test_qemu_runner_rejects_non_qemu_targets(self) -> None:
        result = self.run_pipeline("run-qemu", "--device", "ax23v-v1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("qemu-ovmf-only", result.stderr)

    def test_unlocked_sources_cannot_be_fetched(self) -> None:
        result = self.run_pipeline("fetch", "--device", "ax23v-v1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("status: locked", result.stderr)

    def test_discovery_device_cannot_produce_an_image(self) -> None:
        # Image starts with fetch, so it must fail before touching dist/.
        result = self.run_pipeline("image", "--device", "ax23v-v1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("status: locked", result.stderr)

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
