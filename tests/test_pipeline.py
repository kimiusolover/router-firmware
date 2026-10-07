"""Regression tests for the fail-closed firmware pipeline."""

from __future__ import annotations

import io
import subprocess
import json
import unittest
import unittest.mock
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


class PipelineUnitTests(unittest.TestCase):
    def test_target_required_sources_and_isolation(self) -> None:
        import importlib.util
        spec = importlib.util.spec_from_file_location("pipeline_mod", ROOT / "scripts" / "pipeline.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        # 1. Target fetches only its resolved source dependencies
        resolved_x86 = mod.target_required_sources("x86_64-qemu-uefi-preview", strict=False)
        resolved_names = [v["name"] for _, v in resolved_x86]
        self.assertIn("router-packages", resolved_names)
        self.assertIn("linux", resolved_names)

        # 2. Unrelated pending sources do not block strict resolution if not required
        # If we remove 'linux' from packages.txt of a dummy target that only needs router-packages, strict succeeds
        with unittest.mock.patch.object(mod, "target_required_packages", return_value=["router-packages"]):
            resolved_strict = mod.target_required_sources("x86_64-qemu-uefi-preview", strict=True)
            self.assertEqual(len(resolved_strict), 1)
            self.assertEqual(resolved_strict[0][1]["name"], "router-packages")

        # 3. Required pending source blocks a strict build
        with unittest.mock.patch.object(mod, "target_required_packages", return_value=["linux"]):
            with self.assertRaisesRegex(RuntimeError, "must be status: locked"):
                mod.target_required_sources("x86_64-qemu-uefi-preview", strict=True)

        # 4. Unknown packages fail closed
        with unittest.mock.patch.object(mod, "firmware_device_directory", return_value=ROOT / "devices" / "x86_64-qemu-uefi-preview"):
            with unittest.mock.patch("pathlib.Path.read_text", return_value="unknown-pkg-foo\n"):
                with self.assertRaisesRegex(RuntimeError, "unknown package 'unknown-pkg-foo'"):
                    mod.target_required_packages("x86_64-qemu-uefi-preview")

        # 5. Missing or malformed lock fields fail
        bad_lock = {"name": "test", "status": "locked", "upstream": "https://x.org", "revision": "1", "sha256": "a"*64, "license": "MIT", "archive": "https://x.org/a.tar.gz"}
        bad_lock_missing = dict(bad_lock, name="")
        with self.assertRaisesRegex(RuntimeError, "missing name"):
            mod.validate_source_lock_fields(Path("dummy.yaml"), bad_lock_missing, strict=True)

        # 6. Invalid SHA-256 values rejected
        bad_hash_lock = {"name": "test", "status": "locked", "upstream": "https://x.org", "revision": "1", "sha256": "1234invalid", "license": "MIT", "archive": "https://x.org/a.tar.gz"}
        with self.assertRaisesRegex(RuntimeError, "sha256 must be 64 lowercase hexadecimal characters"):
            mod.validate_source_lock_fields(Path("dummy.yaml"), bad_hash_lock, strict=True)

    def test_fetch_source_archive_caching_and_atomic_downloads(self) -> None:
        import importlib.util
        import tempfile
        import hashlib
        spec = importlib.util.spec_from_file_location("pipeline_mod", ROOT / "scripts" / "pipeline.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        content = b"fake tarball data"
        sha = hashlib.sha256(content).hexdigest()
        source = {
            "name": "fake-pkg",
            "revision": "v1.0",
            "sha256": sha,
            "archive": "https://example.com/fake.tar.gz",
        }

        with tempfile.TemporaryDirectory() as tmp_dir:
            downloads = Path(tmp_dir)

            # 7. Cached archive corruption is detected and cleaned up
            corrupt_file = downloads / "fake-pkg-v1.0.source"
            corrupt_file.write_bytes(b"corrupt data")

            # Mock urllib to return valid content
            class MockResponse:
                def __init__(self, data): self.bio = io.BytesIO(data)
                def __enter__(self): return self
                def __exit__(self, *args): pass
                def read(self, size=-1): return self.bio.read(size)

            with unittest.mock.patch("urllib.request.urlopen", side_effect=lambda url: MockResponse(content)):
                fetched = mod.fetch_source_archive(downloads, source)
                self.assertEqual(fetched.read_bytes(), content)

            # 8. Download failures do not leave valid-looking partial cache entries
            corrupt_source = dict(source, sha256="a"*64)
            with unittest.mock.patch("urllib.request.urlopen", side_effect=lambda url: MockResponse(content)):
                with self.assertRaisesRegex(RuntimeError, "checksum mismatch"):
                    mod.fetch_source_archive(downloads, corrupt_source)
            self.assertFalse((downloads / "fake-pkg-v1.0.source.tmp").exists())

    def test_validate_identifier(self) -> None:
        import importlib.util
        spec = importlib.util.spec_from_file_location("pipeline_mod", ROOT / "scripts" / "pipeline.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        for invalid in ("../escape", "pkg/name", "name;id", "", "pkg\\name"):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(RuntimeError, "invalid characters or empty"):
                    mod.validate_identifier(invalid, "test label")

    def test_unsafe_archive_extraction_rejected(self) -> None:
        import importlib.util
        import io
        import tempfile
        import tarfile
        spec = importlib.util.spec_from_file_location("pipeline_mod", ROOT / "scripts" / "pipeline.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        # Test cases for archive safety
        test_cases = [
            (".", tarfile.DIRTYPE, None, "unsafe or invalid archive member path"),
            ("./some-file", tarfile.REGTYPE, None, "(extraction failed to produce expected directory|router-packages archive must contain)"),
            ("../outside.txt", tarfile.REGTYPE, None, "unsafe or invalid archive member path"),
            ("/abs/path.txt", tarfile.REGTYPE, None, "unsafe archive member path"),
            ("pkg/symlink", tarfile.SYMTYPE, "../../outside.txt", "unsafe archive symlink target"),
            ("pkg/hardlink", tarfile.LNKTYPE, "../outside.txt", "unsafe archive hardlink target"),
            ("pkg/fifo", tarfile.FIFOTYPE, None, "unsafe archive member type"),
        ]

        for member_name, type_flag, linkname, expected_err in test_cases:
            with self.subTest(member_name=member_name):
                with tempfile.TemporaryDirectory() as tmp_dir:
                    tmp_path = Path(tmp_dir)
                    package_sources = tmp_path / "package-sources"
                    package_sources.mkdir(parents=True, exist_ok=True)
                    sentinel = package_sources / "sentinel.txt"
                    sentinel.write_text("unrelated sibling data")

                    tar_path = tmp_path / "bad.tar.gz"

                    with tarfile.open(tar_path, "w:gz") as tar:
                        ti = tarfile.TarInfo(name=member_name)
                        ti.type = type_flag
                        if linkname:
                            ti.linkname = linkname
                        if type_flag == tarfile.REGTYPE:
                            ti.size = 4
                            tar.addfile(ti, io.BytesIO(b"data"))
                        else:
                            tar.addfile(ti)

                    with unittest.mock.patch.object(mod, "target_required_sources", return_value=[(Path("src.yaml"), {"name": "router-packages", "revision": "123"})]):
                        with unittest.mock.patch.object(mod, "fetch_source_archive", return_value=tar_path):
                            with unittest.mock.patch.object(mod, "build_dir", return_value=tmp_path):
                                with self.assertRaisesRegex(RuntimeError, expected_err):
                                    mod.extract_router_packages("x86_64-qemu-uefi-preview")

                    # Assert sentinel file in parent directory remains untouched
                    self.assertTrue(sentinel.is_file())
                    self.assertEqual(sentinel.read_text(), "unrelated sibling data")

    def test_extract_router_packages_preexisting_symlink_rejected(self) -> None:
        import importlib.util
        import io
        import tempfile
        import tarfile
        spec = importlib.util.spec_from_file_location("pipeline_mod", ROOT / "scripts" / "pipeline.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            package_sources = tmp_path / "package-sources"
            package_sources.mkdir(parents=True, exist_ok=True)

            # Create pre-existing symlink at destination
            target_outside = tmp_path / "outside_dir"
            target_outside.mkdir(parents=True, exist_ok=True)
            symlink_dest = package_sources / "router-packages"
            symlink_dest.symlink_to(target_outside)

            tar_path = tmp_path / "valid.tar.gz"
            with tarfile.open(tar_path, "w:gz") as tar:
                ti = tarfile.TarInfo(name="router-packages/foo.txt")
                ti.size = 4
                tar.addfile(ti, io.BytesIO(b"data"))

            with unittest.mock.patch.object(mod, "target_required_sources", return_value=[(Path("src.yaml"), {"name": "router-packages", "revision": "123"})]):
                with unittest.mock.patch.object(mod, "fetch_source_archive", return_value=tar_path):
                    with unittest.mock.patch.object(mod, "build_dir", return_value=tmp_path):
                        with self.assertRaisesRegex(RuntimeError, "destination package_root is a symlink"):
                            mod.extract_router_packages("x86_64-qemu-uefi-preview")

    def test_extract_router_packages_publication_failure_and_rollback(self) -> None:
        import importlib.util
        import io
        import tempfile
        import tarfile
        spec = importlib.util.spec_from_file_location("pipeline_mod", ROOT / "scripts" / "pipeline.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            package_sources = tmp_path / "package-sources"
            package_sources.mkdir(parents=True, exist_ok=True)
            sentinel = package_sources / "sentinel.txt"
            sentinel.write_text("unrelated sibling")

            # Existing package_root with identifiable content
            package_root = package_sources / "router-packages"
            package_root.mkdir(parents=True, exist_ok=True)
            (package_root / "old.txt").write_text("old content v1")

            tar_path = tmp_path / "new.tar.gz"
            with tarfile.open(tar_path, "w:gz") as tar:
                ti = tarfile.TarInfo(name="router-packages/new.txt")
                ti.size = 11
                tar.addfile(ti, io.BytesIO(b"new content"))

            original_rename = Path.rename

            def fail_publish_rename(self, target):
                # Fail only when renaming extracted_dir -> package_root
                if self.name == "router-packages" and Path(target) == package_root:
                    raise OSError("simulated publish rename failure")
                return original_rename(self, target)

            with unittest.mock.patch.object(mod, "target_required_sources", return_value=[(Path("src.yaml"), {"name": "router-packages", "revision": "123"})]):
                with unittest.mock.patch.object(mod, "fetch_source_archive", return_value=tar_path):
                    with unittest.mock.patch.object(mod, "build_dir", return_value=tmp_path):
                        with unittest.mock.patch.object(Path, "rename", autospec=True, side_effect=fail_publish_rename):
                            with self.assertRaisesRegex(RuntimeError, "failed to publish new package_root"):
                                mod.extract_router_packages("x86_64-qemu-uefi-preview")

            # Assert existing file is restored via rollback
            self.assertTrue(package_root.is_dir())
            self.assertTrue((package_root / "old.txt").is_file())
            self.assertEqual((package_root / "old.txt").read_text(), "old content v1")
            self.assertEqual(sentinel.read_text(), "unrelated sibling")

    def test_extract_router_packages_restoration_failure(self) -> None:
        import importlib.util
        import io
        import tempfile
        import tarfile
        spec = importlib.util.spec_from_file_location("pipeline_mod", ROOT / "scripts" / "pipeline.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            package_sources = tmp_path / "package-sources"
            package_sources.mkdir(parents=True, exist_ok=True)
            sentinel = package_sources / "sentinel.txt"
            sentinel.write_text("unrelated sibling")

            # Existing package_root with identifiable content
            package_root = package_sources / "router-packages"
            package_root.mkdir(parents=True, exist_ok=True)
            (package_root / "old.txt").write_text("old content v1")

            tar_path = tmp_path / "new.tar.gz"
            with tarfile.open(tar_path, "w:gz") as tar:
                ti = tarfile.TarInfo(name="router-packages/new.txt")
                ti.size = 11
                tar.addfile(ti, io.BytesIO(b"new content"))

            original_rename = Path.rename

            def fail_both_renames(self, target):
                # Fail rename from package_root -> backup_dir? No, fail publish rename & rollback rename
                if self.name == "router-packages" and Path(target) == package_root:
                    raise OSError("simulated publish failure")
                if self.name.startswith(".backup-router-packages-") and Path(target) == package_root:
                    raise OSError("simulated rollback failure")
                return original_rename(self, target)

            with unittest.mock.patch.object(mod, "target_required_sources", return_value=[(Path("src.yaml"), {"name": "router-packages", "revision": "123"})]):
                with unittest.mock.patch.object(mod, "fetch_source_archive", return_value=tar_path):
                    with unittest.mock.patch.object(mod, "build_dir", return_value=tmp_path):
                        with unittest.mock.patch.object(Path, "rename", autospec=True, side_effect=fail_both_renames):
                            with self.assertRaisesRegex(RuntimeError, "ROLLBACK FAILED"):
                                mod.extract_router_packages("x86_64-qemu-uefi-preview")

            # Backup directory must be retained
            backups = list(package_sources.glob(".backup-router-packages-*"))
            self.assertEqual(len(backups), 1)
            self.assertTrue((backups[0] / "old.txt").is_file())
            self.assertEqual((backups[0] / "old.txt").read_text(), "old content v1")
            self.assertEqual(sentinel.read_text(), "unrelated sibling")

    def test_extract_router_packages_backup_cleanup_failure_retains_new_tree(self) -> None:
        import importlib.util
        import io
        import shutil
        import tempfile
        import tarfile
        spec = importlib.util.spec_from_file_location("pipeline_mod", ROOT / "scripts" / "pipeline.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            package_sources = tmp_path / "package-sources"
            package_sources.mkdir(parents=True, exist_ok=True)

            package_root = package_sources / "router-packages"
            package_root.mkdir(parents=True, exist_ok=True)
            (package_root / "old.txt").write_text("old content v1")

            tar_path = tmp_path / "new.tar.gz"
            with tarfile.open(tar_path, "w:gz") as tar:
                ti = tarfile.TarInfo(name="router-packages/new.txt")
                ti.size = 14
                tar.addfile(ti, io.BytesIO(b"new content v2"))

            original_rmtree = shutil.rmtree

            def fail_backup_rmtree(path, *args, **kwargs):
                path_obj = Path(path)
                if path_obj.name.startswith(".backup-router-packages-"):
                    raise OSError("simulated backup rmtree error")
                return original_rmtree(path, *args, **kwargs)

            with unittest.mock.patch.object(mod, "target_required_sources", return_value=[(Path("src.yaml"), {"name": "router-packages", "revision": "123"})]):
                with unittest.mock.patch.object(mod, "fetch_source_archive", return_value=tar_path):
                    with unittest.mock.patch.object(mod, "build_dir", return_value=tmp_path):
                        with unittest.mock.patch("shutil.rmtree", side_effect=fail_backup_rmtree):
                            res_root, rev = mod.extract_router_packages("x86_64-qemu-uefi-preview")

            # Assert new tree is published and valid, while backup remains
            self.assertEqual(res_root, package_root)
            self.assertTrue((package_root / "new.txt").is_file())
            self.assertEqual((package_root / "new.txt").read_text(), "new content v2")
            self.assertEqual(len(list(package_sources.glob(".backup-router-packages-*"))), 1)

    def test_extract_router_packages_subsequent_run_with_orphaned_backups(self) -> None:
        import importlib.util
        import io
        import tempfile
        import tarfile
        spec = importlib.util.spec_from_file_location("pipeline_mod", ROOT / "scripts" / "pipeline.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            package_sources = tmp_path / "package-sources"
            package_sources.mkdir(parents=True, exist_ok=True)

            # Orphaned backup from previous crashed run
            orphan_backup = package_sources / ".backup-router-packages-orphaned123"
            orphan_backup.mkdir(parents=True, exist_ok=True)
            (orphan_backup / "stale.txt").write_text("orphaned data")

            # Active package_root
            package_root = package_sources / "router-packages"
            package_root.mkdir(parents=True, exist_ok=True)
            (package_root / "old.txt").write_text("old content v1")

            tar_path = tmp_path / "new.tar.gz"
            with tarfile.open(tar_path, "w:gz") as tar:
                ti = tarfile.TarInfo(name="router-packages/new.txt")
                ti.size = 14
                tar.addfile(ti, io.BytesIO(b"new content v2"))

            with unittest.mock.patch.object(mod, "target_required_sources", return_value=[(Path("src.yaml"), {"name": "router-packages", "revision": "123"})]):
                with unittest.mock.patch.object(mod, "fetch_source_archive", return_value=tar_path):
                    with unittest.mock.patch.object(mod, "build_dir", return_value=tmp_path):
                        res_root, rev = mod.extract_router_packages("x86_64-qemu-uefi-preview")

            # Assert new run generates its own UUID backup and leaves orphaned backup untouched
            self.assertEqual(res_root, package_root)
            self.assertTrue((package_root / "new.txt").is_file())
            self.assertTrue(orphan_backup.is_dir())
            self.assertTrue((orphan_backup / "stale.txt").is_file())

    def test_extract_router_packages_successful_replacement(self) -> None:
        import importlib.util
        import io
        import tempfile
        import tarfile
        spec = importlib.util.spec_from_file_location("pipeline_mod", ROOT / "scripts" / "pipeline.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            package_sources = tmp_path / "package-sources"
            package_sources.mkdir(parents=True, exist_ok=True)
            sentinel = package_sources / "sentinel.txt"
            sentinel.write_text("unrelated sibling")

            # Existing package_root with identifiable content
            package_root = package_sources / "router-packages"
            package_root.mkdir(parents=True, exist_ok=True)
            (package_root / "old.txt").write_text("old content v1")

            tar_path = tmp_path / "new.tar.gz"
            with tarfile.open(tar_path, "w:gz") as tar:
                ti = tarfile.TarInfo(name="router-packages/new.txt")
                ti.size = 14
                tar.addfile(ti, io.BytesIO(b"new content v2"))

            with unittest.mock.patch.object(mod, "target_required_sources", return_value=[(Path("src.yaml"), {"name": "router-packages", "revision": "123"})]):
                with unittest.mock.patch.object(mod, "fetch_source_archive", return_value=tar_path):
                    with unittest.mock.patch.object(mod, "build_dir", return_value=tmp_path):
                        res_root, rev = mod.extract_router_packages("x86_64-qemu-uefi-preview")

            self.assertEqual(res_root, package_root)
            self.assertEqual(rev, "123")
            self.assertTrue((package_root / "new.txt").is_file())
            self.assertEqual((package_root / "new.txt").read_text(), "new content v2")
            self.assertFalse((package_root / "old.txt").exists())
            self.assertEqual(len(list(package_sources.glob(".backup-router-packages-*"))), 0)
            self.assertEqual(sentinel.read_text(), "unrelated sibling")
