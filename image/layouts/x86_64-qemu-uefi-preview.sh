#!/usr/bin/env bash
# QEMU preview assembly is unavailable until the locked x86_64 toolchain,
# rootfs, ESP/GPT layout, and reproducible image producer exist.
set -euo pipefail
echo 'x86_64-qemu-uefi-preview: image layout is not implemented; refusing to create a preview image' >&2
echo 'lock sources and toolchain, implement the ESP/GPT layout, then add QEMU E2E evidence' >&2
exit 1
