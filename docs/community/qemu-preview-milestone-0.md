# QEMU preview: serial boot only (Milestone 0)

This document is the canonical, reviewable issue set to create in
`kimiusolover/router-firmware` before requesting outside help. It scopes a
QEMU/OVMF-only x86_64 preview and must never be read as AX23V, physical-PC,
USB, Wi-Fi, Secure Boot, update, rollback, or Web UI support.

## Milestone acceptance criteria

- `routeros-x86_64-uefi-preview.img` is a regular repository-built artifact
  with checked QEMU-only metadata.
- OVMF boots it with a copy-on-write qcow2 overlay only.
- The image presents a login prompt and accepts a documented test login on the
  serial console.
- The launch command has `-display none`, `-serial stdio`, and exactly two
  `e1000e` virtual NICs.
- The result records image SHA-256, OVMF path/version, QEMU version, command,
  serial transcript digest, and the source-lock commit.

## Issue: good first issue — verify source-lock metadata

**Labels:** `good first issue`, `source-lock`, `help wanted`

Verify one source-cache archive at a time. Confirm its exact upstream archive
URL, release/version identifier, SHA-256 (and upstream checksum or signature
evidence), retrieval time, and reviewer identity. Do not download during a
build, substitute a mirror, use `latest`, or lock a partial/corrupt archive.

The current cache entry `linux-6.12.107.tar.xz` fails archive integrity
checking and is explicitly blocked pending a fresh, independently verified
official intake. A contributor may submit metadata and evidence only; no image
assembly, release, signing, flash, or RF action is part of this issue.

## Issue: help wanted — QEMU/OVMF minimal boot design review

**Labels:** `help wanted`, `qemu`, `uefi`, `design-review`

Review the minimal GPT/ESP/rootfs design required to boot to a serial login.
The design must use a virtual disk only, repository-managed qcow2 COW overlay,
serial console only, and no host-block-device or writable OVMF-variable input.
Please identify reproducibility requirements and test evidence. Do not expand
scope to physical PCs, USB, Secure Boot, Wi-Fi, updates, or a Web UI.

## Issue: help wanted — two-NIC DHCP/DNS/firewall E2E test plan

**Labels:** `help wanted`, `qemu`, `e2e`, `networking`

Define the post-Milestone-0 test only: `networkd -> Kea DHCP -> Unbound DNS ->
nftables NAT/firewall` across two `e1000e` NICs. Provide isolated QEMU topology,
expected leases/DNS/NAT assertions, negative firewall assertions, cleanup, and
the serial/log artifacts needed for review. Jool/NAT64, hostapd, and Web UI are
explicitly out of scope.

## Issue: hardware evidence — AX23V non-destructive stock-firmware observations

**Labels:** `hardware evidence`, `ax23v`, `needs human review`

Request only stock-firmware observations: redacted MTD table, boot log,
interface topology, and GPIO/LED/button observations. Do not ask contributors
to flash, dump MTD/calibration/EEPROM, expose MAC addresses or serials, alter
bootloader settings, or transmit RF. Treat all reports as untrusted until human
review; preserve the existing refusal to assemble an AX23V image until partition
geometry, calibration preservation, and boot format are independently verified.
