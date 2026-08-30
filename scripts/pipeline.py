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
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


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
        "format": "router-firmware-unflashable-fixture-v1",
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


def attest(device: str) -> None:
    artifacts = sorted(p for p in (ROOT / "dist").glob(f"{device}*.bin") if p.is_file())
    if not artifacts:
        fail(f"no firmware artifacts for {device}")
    entries = [{"name": p.name, "sha256": hashlib.file_digest(p.open("rb"), "sha256").hexdigest(), "size": p.stat().st_size} for p in artifacts]
    fixture = all(p.read_bytes().startswith(b"ROUTER-FIRMWARE-UNFLASHABLE" + bytes([0])) for p in artifacts)
    if not fixture:
        source_locks(strict=True)
    stamp = os.environ.get("SOURCE_DATE_EPOCH")
    created = datetime.fromtimestamp(int(stamp), timezone.utc).isoformat().replace("+00:00", "Z") if stamp else datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    manifest = {
        "schema": 1,
        "device": device,
        "artifacts": entries,
        "created": created,
        "release_kind": "unflashable-fixture" if fixture else "firmware-image",
        "flashable": False if fixture else True,
        "preserved_partitions": yaml_list(device_paths(device)[1], "preserve"),
    }
    (ROOT / "dist" / f"{device}.manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (ROOT / "dist" / "SHA256SUMS").write_text("".join(f"{entry['sha256']}  {entry['name']}\n" for entry in entries), encoding="utf-8")
    # A plain in-toto Statement lets routerctl verify the same artifact names
    # and digests as the manifest and SHA256SUMS. This is integrity metadata,
    # not a signed attestation; signature verification is a later concern.
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
            "signatureVerification": "not-implemented",
        },
    }
    (ROOT / "dist" / "provenance.json").write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("verify", "fetch", "build", "rootfs", "image", "sample-image", "attest"))
    parser.add_argument("--device", required=True)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    {"verify": lambda: verify(args.device, args.strict), "fetch": lambda: fetch(args.device), "build": lambda: build(args.device), "rootfs": lambda: rootfs(args.device), "image": lambda: image(args.device), "sample-image": lambda: sample_image(args.device), "attest": lambda: attest(args.device)}[args.command]()


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, subprocess.CalledProcessError, OSError) as error:
        print(f"pipeline: {error}", file=sys.stderr)
        sys.exit(1)
