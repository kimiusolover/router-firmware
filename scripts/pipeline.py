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
PLATFORM_ROOT = Path(os.environ.get("ROUTER_PLATFORM_ROOT", str(ROOT.parent / "router-platform"))).resolve()
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


def parse_partitions_yaml(path: Path) -> dict[str, object]:
    """Parse partitions.yaml into a structured python dictionary."""
    result: dict[str, object] = {
        "status": None,
        "media": {},
        "preserve": [],
        "replaceable": [],
        "partitions": [],
    }
    lines = path.read_text(encoding="utf-8").splitlines()
    current_section = None
    current_partition: dict[str, object] | None = None
    current_nvmem: dict[str, object] | None = None

    for raw in lines:
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        indent = len(line) - len(line.lstrip(" "))

        if indent == 0:
            if ":" in stripped and not stripped.startswith("-"):
                key, val = stripped.split(":", 1)
                key = key.strip()
                val = val.strip().strip("'\"")
                current_section = key
                current_partition = None
                current_nvmem = None
                if val:
                    result[key] = val
            continue

        if current_section == "media" and indent >= 2:
            if ":" in stripped:
                k, v = stripped.split(":", 1)
                result["media"][k.strip()] = v.strip().strip("'\"")
            continue

        if current_section in ("preserve", "replaceable") and indent >= 2:
            if stripped.startswith("- "):
                result[current_section].append(stripped[2:].strip().strip("'\""))
            continue

        if current_section == "partitions":
            if indent <= 2 and stripped.startswith("- "):
                current_partition = {}
                result["partitions"].append(current_partition)
                current_nvmem = None
                item = stripped[2:].strip()
                if ":" in item:
                    k, v = item.split(":", 1)
                    val_str = v.strip().strip("'\"") if v.strip() else None
                    if val_str in ("null", "~", ""):
                        val_str = None
                    current_partition[k.strip()] = val_str
            elif current_partition is not None:
                if stripped.startswith("nvmem:"):
                    current_nvmem = None
                    current_partition["nvmem"] = []
                elif current_partition.get("nvmem") is not None and indent >= 6:
                    if stripped.startswith("- "):
                        current_nvmem = {}
                        current_partition["nvmem"].append(current_nvmem)
                        item = stripped[2:].strip()
                        if ":" in item:
                            k, v = item.split(":", 1)
                            val_str = v.strip().strip("'\"") if v.strip() else None
                            if val_str in ("null", "~", ""):
                                val_str = None
                            current_nvmem[k.strip()] = val_str
                    elif current_nvmem is not None and ":" in stripped:
                        k, v = stripped.split(":", 1)
                        val_str = v.strip().strip("'\"") if v.strip() else None
                        if val_str in ("null", "~", ""):
                            val_str = None
                        current_nvmem[k.strip()] = val_str
                elif ":" in stripped:
                    k, v = stripped.split(":", 1)
                    val_str = v.strip().strip("'\"") if v.strip() else None
                    if val_str in ("null", "~", ""):
                        val_str = None
                    current_partition[k.strip()] = val_str

    return result


def parse_num(val: object) -> int:
    if val is None:
        fail("missing integer value")
    if isinstance(val, int):
        return val
    s = str(val).strip().strip("'\"")
    if s.startswith("0x") or s.startswith("0X"):
        return int(s, 16)
    return int(s)


def validate_storage_contract(partitions_path: Path, definition_path: Path) -> dict[str, object]:
    parsed = parse_partitions_yaml(partitions_path)

    status = parsed.get("status")
    if status not in {"discovery", "unverified", "verified"}:
        fail(f"{partitions_path}: invalid status")

    partitions = parsed.get("partitions", [])
    top_preserve = set(parsed.get("preserve", []))
    top_replaceable = set(parsed.get("replaceable", []))

    if partitions:
        names = [p.get("name") for p in partitions if p.get("name") is not None]
        if len(names) != len(partitions):
            fail(f"{partitions_path}: partition missing name")
        if len(names) != len(set(names)):
            fail(f"{partitions_path}: partition names must be unique")

        p_preserve = set()
        p_replaceable = set()
        spans = []

        media = parsed.get("media", {})
        total_bytes = None
        if isinstance(media, dict) and "total_bytes" in media:
            total_bytes = parse_num(media["total_bytes"])

        for p in partitions:
            p_name = str(p.get("name"))
            preservation = p.get("preservation")
            if preservation not in {"preserve", "replaceable"}:
                fail(f"{partitions_path}: partition {p_name} has invalid preservation status: {preservation}")

            if preservation == "preserve":
                p_preserve.add(p_name)
            else:
                p_replaceable.add(p_name)

            try:
                offset = parse_num(p.get("offset"))
                size = parse_num(p.get("size"))
            except (ValueError, TypeError):
                fail(f"{partitions_path}: partition {p_name} has invalid offset or size")

            if offset < 0 or size <= 0:
                fail(f"{partitions_path}: partition {p_name} has invalid offset or size")

            end = offset + size
            if total_bytes is not None and end > total_bytes:
                fail(f"{partitions_path}: partition {p_name} bounds ({hex(offset)}..{hex(end)}) exceed media size ({hex(total_bytes)})")

            spans.append((offset, end, p_name))

        # Overlap check
        spans.sort(key=lambda x: x[0])
        for i in range(len(spans) - 1):
            curr_off, curr_end, curr_name = spans[i]
            next_off, next_end, next_name = spans[i + 1]
            if curr_end > next_off:
                fail(f"{partitions_path}: partitions overlap: {curr_name} ends at {hex(curr_end)} but {next_name} starts at {hex(next_off)}")

        # Check top-level consistency if defined
        if top_preserve and top_preserve != p_preserve:
            fail(f"{partitions_path}: top-level preserve list does not match partition classifications")
        if top_replaceable and top_replaceable != p_replaceable:
            fail(f"{partitions_path}: top-level replaceable list does not match partition classifications")
    else:
        def_preserve = yaml_list(definition_path, "preserve")
        if not top_preserve and not def_preserve:
            fail(f"{partitions_path}: missing preservation policy")

    return parsed


def validate_image_target_region(device: str, target: str | tuple[int, int]) -> None:
    _, definition_path, partitions_path = device_paths(device)
    parsed = validate_storage_contract(partitions_path, definition_path)
    partitions = parsed.get("partitions", [])
    top_preserve = set(parsed.get("preserve", [])) or set(yaml_list(partitions_path, "preserve")) or set(yaml_list(definition_path, "preserve"))

    if isinstance(target, str):
        target_name = target
        preserved_names = {p["name"] for p in partitions if p.get("preservation") == "preserve"} if partitions else top_preserve
        if target_name in preserved_names:
            fail(f"refusing to overwrite preserved partition: {target_name}")
    elif isinstance(target, tuple):
        target_offset, target_end = target
        if partitions:
            for p in partitions:
                if p.get("preservation") == "preserve":
                    p_off = parse_num(p.get("offset"))
                    p_end = p_off + parse_num(p.get("size"))
                    if max(target_offset, p_off) < min(target_end, p_end):
                        fail(f"refusing to overwrite preserved region {p.get('name')} ({hex(p_off)}..{hex(p_end)})")


def get_preserved_partitions(device: str) -> list[str]:
    _, definition_path, partitions_path = device_paths(device)
    parsed = validate_storage_contract(partitions_path, definition_path)
    partitions = parsed.get("partitions", [])
    if partitions:
        return [p["name"] for p in partitions if p.get("preservation") == "preserve"]
    if parsed.get("preserve"):
        return list(parsed["preserve"])
    return yaml_list(partitions_path, "preserve") or yaml_list(definition_path, "preserve")


def fail(message: str) -> None:
    raise RuntimeError(message)


def device_paths(device: str) -> tuple[Path, Path, Path]:
    # Board facts are owned by router-platform. Do not silently read the
    # retired firmware-local copy: a missing checkout must stop the pipeline.
    device_directories = {
        "ax23v-v1": PLATFORM_ROOT / "devices" / "tplink" / "archer-ax23v-v1",
        "x86_64-qemu-uefi-preview": PLATFORM_ROOT / "devices" / "generic" / "x86_64-qemu-uefi-preview",
    }
    directory = device_directories.get(device)
    if directory is None:
        fail(f"unknown platform device: {device}")
    if not directory.is_dir():
        fail(f"platform data unavailable for {device}: {directory}")
    return directory, directory / "device.yaml", directory / "partitions.yaml"


def firmware_device_directory(device: str) -> Path:
    directory = ROOT / "devices" / device
    if not directory.is_dir():
        fail(f"unknown firmware composition: {device}")
    return directory


def input_reference(path: Path) -> str:
    """Return a stable workspace-relative reference for provenance output."""
    try:
        return str(path.relative_to(ROOT.parent))
    except ValueError:
        return str(path)


class PackageDependencySpec:
    """Package dependency specification for source closure resolution.

    Allows declaring explicit source mappings, build-time dependencies,
    runtime dependencies, and kernel dependencies.
    """

    def __init__(
        self,
        name: str,
        source: str | None = None,
        build_deps: tuple[str, ...] = (),
        runtime_deps: tuple[str, ...] = (),
        kernel_deps: tuple[str, ...] = (),
    ) -> None:
        self.name = name
        self.source = source
        self.build_deps = build_deps
        self.runtime_deps = runtime_deps
        self.kernel_deps = kernel_deps

    def required_packages(self) -> set[str]:
        return set(self.build_deps) | set(self.runtime_deps) | set(self.kernel_deps)

    def resolved_source(self) -> str | None:
        return self.source


PACKAGE_REGISTRY: dict[str, PackageDependencySpec] = {
    "linux": PackageDependencySpec("linux", source="linux"),
    "systemd": PackageDependencySpec("systemd", source="systemd"),
    "hostapd": PackageDependencySpec("hostapd", source="hostapd"),
    "nftables": PackageDependencySpec("nftables", source="nftables"),
    "unbound": PackageDependencySpec("unbound", source="unbound"),
    "kea": PackageDependencySpec("kea", source="kea"),
    "jool": PackageDependencySpec("jool", source="jool"),
    "router-packages": PackageDependencySpec("router-packages", source="router-packages"),
    "router": PackageDependencySpec("router", source=None, build_deps=("router-packages",)),
    "base": PackageDependencySpec("base", source=None),
    "kernel": PackageDependencySpec("kernel", source=None, kernel_deps=("linux",)),
    "networking": PackageDependencySpec("networking", source=None),
    "wireless": PackageDependencySpec("wireless", source=None, build_deps=("hostapd",)),
}


def target_required_sources(device: str) -> set[str]:
    """Determine the source lock names required for a device target.

    Computes the deterministic source closure starting from
    devices/<device>/packages.txt and package dependency specs.
    """
    composition = firmware_device_directory(device)
    packages_file = composition / "packages.txt"
    if not packages_file.is_file():
        fail(f"missing {packages_file}")

    requested = [
        line.strip()
        for line in packages_file.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]

    candidates = list(requested)
    recipes_dir = ROOT / "packages"
    if recipes_dir.is_dir():
        for recipe in sorted(recipes_dir.glob("*/build")):
            pkg_name = recipe.parent.name
            if pkg_name not in candidates:
                candidates.append(pkg_name)

    visited_packages: set[str] = set()
    required_sources: set[str] = set()
    queue = list(candidates)

    while queue:
        pkg_name = queue.pop(0)
        if pkg_name in visited_packages:
            continue
        visited_packages.add(pkg_name)

        spec = PACKAGE_REGISTRY.get(pkg_name)
        if spec is None:
            spec = PackageDependencySpec(pkg_name, source=pkg_name)

        source_name = spec.resolved_source()
        if source_name is not None:
            required_sources.add(source_name)

        for dep in sorted(spec.required_packages()):
            if dep not in visited_packages:
                queue.append(dep)

    return required_sources


def source_locks(strict: bool = False, device: str | None = None) -> list[tuple[Path, dict[str, str]]]:
    locks = []
    required = target_required_sources(device) if device is not None else None
    for path in sorted((ROOT / "sources").glob("*.yaml")):
        values = scalar_yaml(path)
        if required is not None and values.get("name") not in required:
            continue
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
    required = ("device.yaml", "partitions.yaml", "regulatory.yaml")
    for name in required:
        if not (directory / name).is_file():
            fail(f"missing {directory / name}")
    composition = firmware_device_directory(device)
    for name in ("kernel.config", "packages.txt"):
        if not (composition / name).is_file():
            fail(f"missing {composition / name}")
    definition = scalar_yaml(definition_path)
    if definition.get("id") != device:
        fail(f"{definition_path}: id must equal {device}")
    if definition.get("status") not in {"discovery", "verified", "supported"}:
        fail(f"{definition_path}: invalid status")

    validate_storage_contract(partitions_path, definition_path)

    locks = source_locks(strict, device=device)
    names = {values["name"] for _, values in locks}
    requested = {
        line.strip() for line in (composition / "packages.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    missing = requested - names
    if missing:
        fail(f"{composition / 'packages.txt'}: no source lock for {', '.join(sorted(missing))}")


def build_dir(device: str) -> Path:
    path = ROOT / "build" / device
    path.mkdir(parents=True, exist_ok=True)
    return path


def fetch(device: str) -> None:
    verify(device, strict=True)
    downloads = build_dir(device) / "downloads"
    downloads.mkdir(exist_ok=True)
    for _, source in source_locks(strict=True, device=device):
        destination = downloads / f"{source['name']}-{source['revision']}.source"
        if not destination.exists():
            print(f"fetch {source['name']}")
            with urllib.request.urlopen(source["archive"]) as response, destination.open("wb") as output:
                shutil.copyfileobj(response, output)
        digest = hashlib.file_digest(destination.open("rb"), "sha256").hexdigest()
        if digest != source["sha256"]:
            destination.unlink(missing_ok=True)
            fail(f"checksum mismatch for {source['name']}")


def extract_router_packages(device: str) -> tuple[Path, str]:
    """Extract the locked internal router-packages archive for recipe use."""
    source = next(
        values for _, values in source_locks(strict=True, device=device)
        if values["name"] == "router-packages"
    )
    archive = build_dir(device) / "downloads" / f"router-packages-{source['revision']}.source"
    package_root = build_dir(device) / "package-sources" / "router-packages"
    shutil.rmtree(package_root, ignore_errors=True)
    package_root.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, mode="r:*") as bundle:
        members = bundle.getmembers()
        if not members:
            fail("router-packages archive is empty")
        roots = {member.name.split("/", 1)[0] for member in members if member.name}
        if len(roots) != 1:
            fail("router-packages archive must contain exactly one top-level directory")
        bundle.extractall(package_root.parent, filter="data")
    extracted = package_root.parent / next(iter(roots))
    if extracted != package_root:
        extracted.rename(package_root)
    return package_root, source["revision"]


def build(device: str) -> None:
    fetch(device)
    recipes = sorted((ROOT / "packages").glob("*/build"))
    if not recipes:
        fail("no package build recipes found; add packages/<group>/build")
    env = {
        "PATH": os.environ["PATH"],
        "SOURCE_DATE_EPOCH": os.environ.get("SOURCE_DATE_EPOCH", "0"),
        "BUILD_DIR": str(build_dir(device)),
        "DEVICE": device,
    }
    router_packages_root, router_packages_revision = extract_router_packages(device)
    env["ROUTER_PACKAGES_ROOT"] = str(router_packages_root)
    env["ROUTER_PACKAGES_REVISION"] = router_packages_revision
    for recipe in recipes:
        if not os.access(recipe, os.X_OK):
            fail(f"build recipe is not executable: {recipe}")
        subprocess.run([str(recipe)], cwd=ROOT, env=env, check=True)


def stage_rootfs(device: str, destination: Path) -> None:
    """Compose files without executing target programs or changing host accounts."""
    shutil.rmtree(destination, ignore_errors=True)
    shutil.copytree(ROOT / "rootfs", destination, symlinks=True)
    overlay = ROOT / "overlays" / device
    if overlay.is_dir():
        shutil.copytree(overlay, destination, dirs_exist_ok=True, symlinks=True)
    package_rootfs = build_dir(device) / "package-rootfs"
    if package_rootfs.is_dir():
        shutil.copytree(package_rootfs, destination, dirs_exist_ok=True, symlinks=True)
    if device == "x86_64-qemu-uefi-preview":
        # Git does not preserve these modes. Final image assembly must assign
        # root ownership to /etc and uid/gid 1000 to /home/admin.
        (destination / "etc/shadow").chmod(0o600)
        (destination / "etc/sudoers").chmod(0o440)
        (destination / "etc/sudoers.d/admin").chmod(0o440)
        (destination / "home/admin").mkdir(parents=True, exist_ok=True)
        (destination / "home/admin").chmod(0o700)
    etc = destination / "etc"
    etc.mkdir(exist_ok=True)
    (etc / "router-firmware-build.json").write_text(json.dumps({"device": device, "source_date_epoch": os.environ.get("SOURCE_DATE_EPOCH", "0")}, sort_keys=True) + "\n", encoding="utf-8")


def rootfs(device: str) -> None:
    build(device)
    stage_rootfs(device, build_dir(device) / "rootfs")


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


def run_qemu(device: str, execute: bool = False) -> None:
    """Prepare, or explicitly start, the isolated x86_64 preview VM."""
    _, definition_path, _ = device_paths(device)
    definition = scalar_yaml(definition_path)
    if definition.get("deployment") != "qemu-ovmf-only":
        fail(f"{device}: run-qemu is allowed only for qemu-ovmf-only targets")
    image_name = definition.get("preview_image")
    if not image_name or "/" in image_name or not image_name.endswith(".img"):
        fail(f"{definition_path}: preview_image must be a simple .img filename")
    image_path = ROOT / "dist" / image_name
    metadata_path = ROOT / "dist" / f"{image_name}.qemu.json"
    if not image_path.is_file() or image_path.is_symlink() or not metadata_path.is_file() or metadata_path.is_symlink():
        fail("QEMU preview image and its qemu metadata must be built before run-qemu")
    from preview_vm import validate_image, fresh_storage
    try:
        image_path, metadata = validate_image(ROOT, image_name)
        qemu_img, qemu = shutil.which("qemu-img"), shutil.which("qemu-system-x86_64")
        if not qemu_img or not qemu or not os.environ.get("OVMF_CODE") or not os.environ.get("OVMF_VARS"):
            fail("QEMU, qemu-img, OVMF_CODE and OVMF_VARS template are required")
        session, overlay = fresh_storage(ROOT, image_path, metadata, qemu_img,
            Path(os.environ["OVMF_CODE"]).resolve(), Path(os.environ["OVMF_VARS"]).resolve())
        ovmf_path = session / "OVMF_CODE.fd"
    except (ValueError, OSError) as error:
        fail(str(error))
    # Milestone 0 is deliberately serial-only. e1000e is used instead of
    # virtio-net because it is the driver family required by the preview
    # kernel contract; the two interfaces are reserved for the later WAN/LAN
    # DHCP/DNS/firewall E2E milestone.
    command = [qemu, "-machine", "q35", "-m", "1024", "-display", "none", "-serial", "stdio", "-drive", f"if=pflash,format=raw,readonly=on,file={ovmf_path}", "-drive", f"if=pflash,format=raw,file={session / 'OVMF_VARS.fd'}", "-drive", f"if=virtio,format=qcow2,file={overlay}", "-nic", "user,model=e1000e", "-nic", "user,model=e1000e"]
    if execute:
        subprocess.run(command, cwd=ROOT, check=True)
    else:
        print("QEMU command prepared; rerun with --execute to start the isolated VM:")
        print(" ".join(command))


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
        "inputs": {name: input_reference(path) for name, path in paths.items()},
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
    composition = firmware_device_directory(device)
    if not capability_path.is_file(): fail(f"missing tiny capability input: {capability_path}")
    inputs = {"device": yaml_truths(capability_path), "certification": yaml_truths(cert_path) if cert_path.is_file() else {}, "deployment": {}}
    if deployment_policy:
        policy_path = Path(deployment_policy).resolve()
        if not policy_path.is_file(): fail(f"deployment policy is not a file: {policy_path}")
        inputs["deployment"] = yaml_truths(policy_path)
    requested = {line.strip() for line in (composition / "packages.txt").read_text(encoding="utf-8").splitlines() if line.strip() and not line.lstrip().startswith("#")}
    profiles: list[dict[str, object]] = []
    for path in sorted((ROOT / "tiny").glob("*/features.yaml")):
        policy = tiny_feature_policy(path); package = str(policy["package"])
        if package not in requested: fail(f"{path}: package is not in {composition / 'packages.txt'}")
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
    plan = {"schema": "router-firmware.tiny-plan/v1", "device": device, "status": "proposed", "image_authorized": False, "profiles": profiles, "inputs": {"device": input_reference(capability_path), "certification": input_reference(cert_path) if cert_path.is_file() else "unset", "deployment": deployment_policy or "unset"}}
    output = build_dir(device) / "tiny.plan.json"; output.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8"); print(output.relative_to(ROOT))


def write_sbom(device: str, fixture: bool, entries: list[dict[str, object]], created: str) -> Path:
    """Emit a deterministic CycloneDX inventory for the release artifact set."""
    components = [{
        "type": "file",
        "name": entry["name"],
        "hashes": [{"alg": "SHA-256", "content": entry["sha256"]}],
        "properties": [{"name": "router-firmware:format", "value": entry["format"]}],
    } for entry in entries]
    for _, source in source_locks(not fixture, device=device):
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
        source_locks(strict=True, device=device)
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
        "preserved_partitions": get_preserved_partitions(device),
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
            "sources": [v for _, v in source_locks(not fixture, device=device)],
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
    parser.add_argument("command", choices=("verify", "fetch", "build", "rootfs", "image", "sample-image", "attest", "plan-storage", "plan-tiny", "run-qemu"))
    parser.add_argument("--device", required=True)
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--deployment-policy")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    {"verify": lambda: verify(args.device, args.strict), "fetch": lambda: fetch(args.device), "build": lambda: build(args.device), "rootfs": lambda: rootfs(args.device), "image": lambda: image(args.device), "sample-image": lambda: sample_image(args.device), "attest": lambda: attest(args.device), "plan-storage": lambda: plan_storage(args.device), "plan-tiny": lambda: plan_tiny(args.device, args.deployment_policy), "run-qemu": lambda: run_qemu(args.device, args.execute)}[args.command]()


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, subprocess.CalledProcessError, OSError) as error:
        print(f"pipeline: {error}", file=sys.stderr)
        sys.exit(1)
