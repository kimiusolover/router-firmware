#!/usr/bin/env python3
"""Reproducible, guarded firmware build pipeline.

This tool deliberately treats device images as an opt-in final stage.  It can
fetch locked source archives and construct a deterministic rootfs workspace,
but it will never write a flashable artifact until the device definition and
partition map say that the target is supported and verified.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_FORMATS = {
    "tplink-safeloader",
    "openwrt-sysupgrade",
    "router-firmware-unflashable-fixture",
}


def scalar_yaml(path: Path) -> dict[str, str]:
    """Load the flat scalar fields used by device and source lock files."""
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or ":" not in line or line.startswith("-"):
            continue
        key, value = line.split(":", 1)
        values[key.strip()] = value.strip().strip("'\"")
    return values


def yaml_list(path: Path, key: str) -> list[str]:
    """Read a simple top-level YAML list without accepting arbitrary YAML."""
    values: list[str] = []
    collecting = False
    for raw in path.read_text(encoding="utf-8").splitlines():
        if raw.startswith(f"{key}:"):
            collecting = True
            continue
        if collecting and raw.startswith("  - "):
            values.append(raw[4:].strip().strip("'\""))
            continue
        if collecting and raw and not raw.startswith(" ") and not raw.startswith("#"):
            break
    return values


def fail(message: str) -> None:
    raise RuntimeError(message)


def device_paths(device: str) -> tuple[Path, Path, Path]:
    directory = ROOT / "devices" / device
    if not directory.is_dir():
        fail(f"unknown device: {device}")
    return directory, directory / "device.yaml", directory / "partitions.yaml"


def source_locks(strict: bool) -> list[tuple[Path, dict[str, str]]]:
    locks = []
    for path in sorted((ROOT / "sources").glob("*.yaml")):
        values = scalar_yaml(path)
        for field in ("name", "status", "upstream", "revision", "sha256", "license", "archive"):
            if not values.get(field):
                fail(f"{path}: missing {field}")
        if strict:
            if values["status"] != "locked":
                fail(f"{path}: source must be status: locked before this stage")
            for field in ("upstream", "revision", "sha256", "archive"):
                if values[field] == "unset":
                    fail(f"{path}: {field} must be pinned before this stage")
            digest = values["sha256"]
            if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                fail(f"{path}: sha256 must be 64 lowercase hexadecimal characters")
            if not values["archive"].startswith("https://"):
                fail(f"{path}: archive must use HTTPS")
        locks.append((path, values))
    if not locks:
        fail("no source locks found")
    return locks


def verify(device: str, strict: bool = False) -> None:
    directory, definition_path, partitions_path = device_paths(device)
    required = ("device.yaml", "partitions.yaml", "kernel.config", "packages.txt", "regulatory.yaml")
    for name in required:
        if not (directory / name).is_file():
            fail(f"missing {directory / name}")
    definition = scalar_yaml(definition_path)
    partitions = scalar_yaml(partitions_path)
    if definition.get("id") != device:
        fail(f"{definition_path}: id must equal {device}")
    if definition.get("status") not in {"discovery", "verified", "supported"}:
        fail(f"{definition_path}: invalid status")
    if partitions.get("status") not in {"unverified", "verified"}:
        fail(f"{partitions_path}: invalid status")
    text = definition_path.read_text(encoding="utf-8")
    for name in ("u-boot", "factory", "art"):
        if name not in text:
            fail(f"{definition_path}: preserved region {name} is required")
    locks = source_locks(strict)
    names = {values["name"] for _, values in locks}
    requested = {
        line.strip() for line in (directory / "packages.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    missing = requested - names
    if missing:
        fail(f"{directory / 'packages.txt'}: no source lock for {', '.join(sorted(missing))}")


def build_dir(device: str) -> Path:
    path = ROOT / "build" / device
    path.mkdir(parents=True, exist_ok=True)
    return path


def fetch(device: str) -> None:
    verify(device, strict=True)
    downloads = build_dir(device) / "downloads"
    downloads.mkdir(exist_ok=True)
    for _, source in source_locks(strict=True):
        destination = downloads / f"{source['name']}-{source['revision']}.source"
        if not destination.exists():
            print(f"fetch {source['name']}")
            with urllib.request.urlopen(source["archive"]) as response, destination.open("wb") as output:
                shutil.copyfileobj(response, output)
        digest = hashlib.file_digest(destination.open("rb"), "sha256").hexdigest()
        if digest != source["sha256"]:
            destination.unlink(missing_ok=True)
            fail(f"checksum mismatch for {source['name']}")


def build(device: str) -> None:
    fetch(device)
    recipes = sorted((ROOT / "packages").glob("*/build"))
    if not recipes:
        fail("no package build recipes found; add packages/<group>/build")
    env = {"PATH": os.environ["PATH"], "SOURCE_DATE_EPOCH": os.environ.get("SOURCE_DATE_EPOCH", "0"), "BUILD_DIR": str(build_dir(device)), "DEVICE": device}
    for recipe in recipes:
        if not os.access(recipe, os.X_OK):
            fail(f"build recipe is not executable: {recipe}")
        subprocess.run([str(recipe)], cwd=ROOT, env=env, check=True)


def rootfs(device: str) -> None:
    build(device)
    destination = build_dir(device) / "rootfs"
    shutil.rmtree(destination, ignore_errors=True)
    shutil.copytree(ROOT / "rootfs", destination, symlinks=True)
    overlay = ROOT / "overlays" / device
    if overlay.is_dir():
        shutil.copytree(overlay, destination, dirs_exist_ok=True, symlinks=True)
    etc = destination / "etc"
    etc.mkdir(exist_ok=True)
    (etc / "router-firmware-build.json").write_text(json.dumps({"device": device, "source_date_epoch": os.environ.get("SOURCE_DATE_EPOCH", "0")}, sort_keys=True) + "\n", encoding="utf-8")


def image(device: str) -> None:
    rootfs(device)
    _, definition_path, partitions_path = device_paths(device)
    definition, partitions = scalar_yaml(definition_path), scalar_yaml(partitions_path)
    if definition.get("status") != "supported" or partitions.get("status") != "verified":
        fail("refusing image assembly: device and partition map must be supported/verified")
    layout = ROOT / "image" / "layouts" / f"{device}.sh"
    if not layout.is_file() or not os.access(layout, os.X_OK):
        fail(f"missing executable image layout: {layout}")
    subprocess.run([str(layout), str(build_dir(device) / "rootfs"), str(ROOT / "dist")], cwd=ROOT, check=True)


def sample_image(device: str) -> None:
    """Create a deterministic fixture which cannot be a router flash image.

    It exists to exercise artifact handling before board evidence is available.
    The identifying header is deliberately incompatible with TP-Link formats.
    """
    verify(device)
    _, definition_path, _ = device_paths(device)
    definition = scalar_yaml(definition_path)
    if definition.get("status") != "discovery":
        fail("sample images are allowed only for discovery targets")

    epoch = int(os.environ.get("SOURCE_DATE_EPOCH", "0"))
    staging = build_dir(device) / "sample-rootfs"
    shutil.rmtree(staging, ignore_errors=True)
    shutil.copytree(ROOT / "rootfs", staging, symlinks=True)
    overlay = ROOT / "overlays" / device
    if overlay.is_dir():
        shutil.copytree(overlay, staging, dirs_exist_ok=True, symlinks=True)

    output = ROOT / "dist" / f"{device}.bin"
    header = {
        "device": device,
        "format": "router-firmware-unflashable-fixture",
        "reason": "AX23V partition map, boot format, and signing are unverified",
        "source_date_epoch": epoch,
    }
    with output.open("wb") as artifact:
        artifact.write(b"ROUTER-FIRMWARE-UNFLASHABLE" + bytes([0]))
        artifact.write(json.dumps(header, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        artifact.write(b"\\n")
        with tarfile.open(fileobj=artifact, mode="w|") as archive:
            for path in sorted(staging.rglob("*")):
                info = archive.gettarinfo(str(path), arcname=str(path.relative_to(staging)))
                info.uid = info.gid = 0
                info.uname = info.gname = "root"
                info.mtime = epoch
                if info.isfile():
                    with path.open("rb") as source:
                        archive.addfile(info, source)
                else:
                    archive.addfile(info)


def plan_storage(device: str) -> None:
    """Emit a fail-closed storage-layout proposal and finalization blockers.

    This intentionally does not solve offsets or sizes from device guesses.
    A proposal is useful as an auditable planning artifact; it is never an
    image authorization and remains non-flashable until the capability record
    and capacity allocations are fully verified.
    """
    verify(device)
    directory, definition_path, _ = device_paths(device)
    paths = {
        "storage_specification": ROOT / "docs" / "storage-specification.yaml",
        "storage_policy": directory / "storage-policy.yaml",
        "capacity_specification": ROOT / "docs" / "capacity-allocation-specification.yaml",
        "capacity_policy": directory / "capacity-policy.yaml",
        "storage_capabilities": directory / "storage-capabilities.yaml",
        "planner_specification": ROOT / "docs" / "layout-planner-specification.yaml",
    }
    for label, path in paths.items():
        if not path.is_file():
            fail(f"missing {label}: {path}")

    capabilities = paths["storage_capabilities"].read_text(encoding="utf-8")
    capacity = paths["capacity_policy"].read_text(encoding="utf-8")
    definition = scalar_yaml(definition_path)
    blockers: list[dict[str, object]] = []

    def block(code: str, message: str, affected: list[str]) -> None:
        blockers.append({"code": code, "message": message, "affected_classes": affected})

    if "total_bytes: unset" in capabilities:
        block("physical_media_unverified", "physical media capacity is unset", ["SYSTEM", "CONFIG", "STATE", "RECOVERY"])
    if "physical_regions: []" in capabilities:
        block("mtd_boundaries_unverified", "no evidence-backed physical-region boundaries are available", ["BOOT", "DEVICE_DATA", "SYSTEM", "RECOVERY"])
    if "bootloader_visible_regions: []" in capabilities:
        block("bootloader_visible_regions_unverified", "bootloader-visible regions are not verified", ["BOOT", "RECOVERY"])
    if "safely_allocatable: unset" in capabilities or "oom_reserve: unset" in capabilities:
        block("ram_budget_unverified", "RAM budget or OOM reserve is unset", ["LOG", "CACHE"])
    if any(f"{field}: unset" in capacity for field in ("min", "target", "max", "reserve")):
        block("capacity_allocations_unset", "per-class capacity allocation contains unset values", ["SYSTEM", "CONFIG", "STATE", "LOG", "CACHE", "RECOVERY"])
    if definition.get("status") != "supported":
        block("device_not_supported", "device is not supported for final storage layout", ["BOOT", "DEVICE_DATA", "SYSTEM", "CONFIG", "STATE", "LOG", "CACHE", "RECOVERY"])

    classes = ("BOOT", "DEVICE_DATA", "SYSTEM", "CONFIG", "STATE", "LOG", "CACHE", "RECOVERY")
    plan = {
        "schema": "router-firmware.storage-layout-plan/v1",
        "device": device,
        "status": "proposed",
        "regions": [{"class": name, "placement": "unset", "offset": "unset", "size": "unset", "resource": "unset"} for name in classes],
        "validation": {
            "flashable": False,
            "final_eligible": not blockers,
            "blockers": [entry["code"] for entry in blockers],
        },
        "rejection_report": {"accepted": not blockers, "reasons": blockers},
        "inputs": {name: str(path.relative_to(ROOT)) for name, path in paths.items()},
    }
    output = build_dir(device) / "storage-layout.plan.json"
    output.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(output.relative_to(ROOT))


def tiny_feature_policy(path: Path) -> dict[str, object]:
    """Parse the deliberately small YAML subset used by tiny feature policy."""
    result: dict[str, object] = {"required": [], "conditional": [], "excluded": [], "upstream-required": []}
    section = nested = None
    current: dict[str, object] | None = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line, stripped = raw.rstrip(), raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not line.startswith(" ") and ":" in line:
            key, value = line.split(":", 1)
            section, nested, current = key, None, None
            if value.strip(): result[key] = value.strip().strip("'\"")
        elif section in {"required", "excluded", "upstream-required"} and line.startswith("  - "):
            result[section].append(stripped[2:].strip())
        elif section == "conditional" and line.startswith("  - feature:"):
            current = {"feature": line.split(":", 1)[1].strip(), "requires": []}; result["conditional"].append(current)
        elif section == "conditional" and line.startswith("    requires:") and current is not None:
            nested = "requires"
        elif section == "conditional" and nested == "requires" and line.startswith("      - ") and current is not None:
            current["requires"].append(stripped[2:].strip())
        elif section in {"binaries", "units"} and line.startswith("  required:"):
            result[section] = []; nested = "required"
        elif section in {"binaries", "units"} and nested == "required" and line.startswith("    - "):
            result[section].append(stripped[2:].strip())
        else:
            fail(f"{path}: unsupported tiny policy syntax: {raw}")
    for field in ("schema", "package", "required", "conditional", "excluded", "upstream-required"):
        if not result.get(field): fail(f"{path}: missing or empty {field}")
    if result["schema"] != "router-firmware.tiny-features/v1": fail(f"{path}: unsupported schema")
    names = set(result["required"]) | {str(item["feature"]) for item in result["conditional"]}
    for field in ("excluded", "upstream-required"):
        overlap = names.intersection(result[field])
        if overlap: fail(f"{path}: feature classified more than once: {', '.join(sorted(overlap))}")
    return result


def yaml_truths(path: Path) -> dict[str, bool]:
    """Flatten true/false scalar input; unset, missing, and unknown are false."""
    values: dict[str, bool] = {}; parents: list[tuple[int, str]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip() or raw.lstrip().startswith("#") or ":" not in raw: continue
        indent = len(raw) - len(raw.lstrip(" ")); key, value = raw.strip().split(":", 1)
        while parents and parents[-1][0] >= indent: parents.pop()
        if value.strip(): values[".".join([part for _, part in parents] + [key])] = value.strip().lower() == "true"
        else: parents.append((indent, key))
    return values


def plan_tiny(device: str, deployment_policy: str | None = None) -> None:
    """Emit proposal-only package profiles; this never authorizes a build or image."""
    verify(device)
    directory, _, _ = device_paths(device); capability_path = directory / "tiny-capabilities.yaml"; cert_path = directory / "certification-profile.yaml"
    if not capability_path.is_file(): fail(f"missing tiny capability input: {capability_path}")
    inputs = {"device": yaml_truths(capability_path), "certification": yaml_truths(cert_path) if cert_path.is_file() else {}, "deployment": {}}
    if deployment_policy:
        policy_path = Path(deployment_policy).resolve()
        if not policy_path.is_file(): fail(f"deployment policy is not a file: {policy_path}")
        inputs["deployment"] = yaml_truths(policy_path)
    requested = {line.strip() for line in (directory / "packages.txt").read_text(encoding="utf-8").splitlines() if line.strip() and not line.lstrip().startswith("#")}
    profiles: list[dict[str, object]] = []
    for path in sorted((ROOT / "tiny").glob("*/features.yaml")):
        policy = tiny_feature_policy(path); package = str(policy["package"])
        if package not in requested: fail(f"{path}: package is not in {directory / 'packages.txt'}")
        selected, unresolved = list(policy["required"]), []
        for conditional in policy["conditional"]:
            requirements = list(conditional["requires"])
            missing = [name for name in requirements if not inputs.get(name.split(".", 1)[0], {}).get(name.split(".", 1)[1], False)]
            if missing: unresolved.append({"feature": conditional["feature"], "missing_requirements": missing})
            else: selected.append(conditional["feature"])
        profile: dict[str, object] = {"package": package, "selected": selected, "excluded": policy["excluded"], "upstream_required": policy["upstream-required"], "unresolved_conditionals": unresolved}
        for name in ("binaries", "units"):
            if name in policy: profile[f"{name}_allowlist"] = policy[name]
        profiles.append(profile)
    plan = {"schema": "router-firmware.tiny-plan/v1", "device": device, "status": "proposed", "image_authorized": False, "profiles": profiles, "inputs": {"device": str(capability_path.relative_to(ROOT)), "certification": str(cert_path.relative_to(ROOT)) if cert_path.is_file() else "unset", "deployment": deployment_policy or "unset"}}
    output = build_dir(device) / "tiny.plan.json"; output.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8"); print(output.relative_to(ROOT))


def write_sbom(device: str, fixture: bool, entries: list[dict[str, object]], created: str) -> Path:
    """Emit a deterministic CycloneDX inventory for the release artifact set."""
    components = [{
        "type": "file",
        "name": entry["name"],
        "hashes": [{"alg": "SHA-256", "content": entry["sha256"]}],
        "properties": [{"name": "router-firmware:format", "value": entry["format"]}],
    } for entry in entries]
    for _, source in source_locks(not fixture):
        components.append({
            "type": "library",
            "name": source["name"],
            "version": source["revision"],
            "externalReferences": [{"type": "distribution", "url": source["archive"]}],
            "hashes": [{"alg": "SHA-256", "content": source["sha256"]}],
            "licenses": [{"license": {"name": source["license"]}}],
        })
    sbom = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "serialNumber": f"urn:uuid:{uuid.uuid5(uuid.NAMESPACE_URL, f'https://router-firmware.invalid/sbom/{device}')}",
        "version": 1,
        "metadata": {
            "timestamp": created,
            "component": {"type": "firmware", "name": f"router-firmware-{device}"},
            "properties": [
                {"name": "router-firmware:release-kind", "value": "unflashable-fixture" if fixture else "firmware-image"},
                {"name": "router-firmware:flashable", "value": str(not fixture).lower()},
            ],
        },
        "components": components,
    }
    path = ROOT / "dist" / f"{device}.sbom.cdx.json"
    path.write_text(json.dumps(sbom, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def attest(device: str) -> None:
    artifacts = sorted(p for p in (ROOT / "dist").glob(f"{device}*.bin") if p.is_file())
    if not artifacts:
        fail(f"no firmware artifacts for {device}")
    definition = scalar_yaml(device_paths(device)[1])
    partitions = scalar_yaml(device_paths(device)[2])
    fixture = all(p.read_bytes().startswith(b"ROUTER-FIRMWARE-UNFLASHABLE" + bytes([0])) for p in artifacts)
    if not fixture and (definition.get("status") != "supported" or partitions.get("status") != "verified"):
        fail("refusing artifact attestation: device and partition map must be supported/verified")
    image_format = "router-firmware-unflashable-fixture" if fixture else definition.get("format", "")
    if image_format not in ARTIFACT_FORMATS:
        fail(f"unsupported artifact format: {image_format or 'unset'}")
    entries: list[dict[str, object]] = [{
        "name": p.name,
        "sha256": hashlib.file_digest(p.open("rb"), "sha256").hexdigest(),
        "size": p.stat().st_size,
        "format": image_format,
    } for p in artifacts]
    if not fixture:
        source_locks(strict=True)
    stamp = os.environ.get("SOURCE_DATE_EPOCH")
    created = datetime.fromtimestamp(int(stamp), timezone.utc).isoformat().replace("+00:00", "Z") if stamp else datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    sbom = write_sbom(device, fixture, entries, created)
    entries.append({
        "name": sbom.name,
        "sha256": hashlib.file_digest(sbom.open("rb"), "sha256").hexdigest(),
        "size": sbom.stat().st_size,
        "format": "cyclonedx-1.5-json",
    })
    manifest = {
        "schema": 2,
        "device": device,
        "artifacts": entries,
        "created": created,
        "release_kind": "unflashable-fixture" if fixture else "firmware-image",
        "flashable": False if fixture else True,
        "preserved_partitions": yaml_list(device_paths(device)[1], "preserve"),
    }
    (ROOT / "dist" / f"{device}.manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (ROOT / "dist" / "SHA256SUMS").write_text("".join(f"{entry['sha256']}  {entry['name']}\n" for entry in entries), encoding="utf-8")
    # GitHub Actions signs the release artifact plus manifest and SBOM using
    # keyless Sigstore in the release workflow. This file remains the unsigned
    # payload so routerctl can verify metadata agreement without network access.
    provenance = {
        "_type": "https://in-toto.io/Statement/v1",
        "subject": [{"name": entry["name"], "digest": {"sha256": entry["sha256"]}} for entry in entries],
        "predicateType": "https://routerctl.dev/firmware-provenance/v1",
        "predicate": {
            "device": device,
            "releaseKind": "unflashable-fixture" if fixture else "firmware-image",
            "sourceDateEpoch": stamp or None,
            "sources": [v for _, v in source_locks(not fixture)],
            "verifier": {
                "repository": "kimiusolover/routerctl",
                "commit": os.environ.get("ROUTERCTL_VERIFIER_COMMIT"),
            },
            "signatureVerification": "required-for-release",
            # Optional contributor provenance. These fields preserve the
            # existing in-toto statement shape and are set when known.
            "generator": os.environ.get("ROUTEROS_GENERATOR", "router-firmware pipeline attest"),
            "automation_actor": os.environ.get("ROUTEROS_AUTOMATION_ACTOR"),
            "ai_assistance": os.environ.get("ROUTEROS_AI_ASSISTANCE"),
            "human_review": {
                "required": os.environ.get("ROUTEROS_HUMAN_REVIEW_REQUIRED", "true").lower() == "true",
                "reviewed_by": os.environ.get("ROUTEROS_REVIEWED_BY"),
            },
        },
    }
    (ROOT / "dist" / "provenance.json").write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("verify", "fetch", "build", "rootfs", "image", "sample-image", "attest", "plan-storage", "plan-tiny"))
    parser.add_argument("--device", required=True)
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--deployment-policy")
    args = parser.parse_args()
    {"verify": lambda: verify(args.device, args.strict), "fetch": lambda: fetch(args.device), "build": lambda: build(args.device), "rootfs": lambda: rootfs(args.device), "image": lambda: image(args.device), "sample-image": lambda: sample_image(args.device), "attest": lambda: attest(args.device), "plan-storage": lambda: plan_storage(args.device), "plan-tiny": lambda: plan_tiny(args.device, args.deployment_policy)}[args.command]()


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, subprocess.CalledProcessError, OSError) as error:
        print(f"pipeline: {error}", file=sys.stderr)
        sys.exit(1)
