#!/usr/bin/env bash
# This layout is intentionally a safety gate, not a provisional flash writer.
# It can only be replaced when partitions.yaml is independently verified.
set -euo pipefail

echo "ax23v-v1: image layout is not implemented; refusing to create firmware" >&2
echo "verify SoC, stock-image format, partition offsets and preserved regions first" >&2
exit 1
