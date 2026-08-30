# router-firmware

Reproducible firmware composition for supported routers. This repository owns
the product configuration, source locks, patches, root filesystem policy, and
image assembly. Upstream projects (Linux, systemd, hostapd, and others) remain
external sources rather than being vendored here.

## Supported target

`ax23v-v1` is the initial target. It is intentionally **not buildable into a
flashable image yet**: the partition map, signed-image format, SoC support,
source revisions, and verification procedure must be established from primary
materials first.

The following device-specific data must never be created, replaced, or bundled
into a release image:

- U-Boot and its environment
- Ethernet MAC addresses
- Wi-Fi calibration / ART data
- TP-Link factory and vendor-reserved partitions

## Commands

```sh
make help
make verify DEVICE=ax23v-v1
make build DEVICE=ax23v-v1
```

To exercise release tooling before the hardware facts are available:

```sh
SOURCE_DATE_EPOCH=0 make sample-image DEVICE=ax23v-v1
```

This writes `dist/ax23v-v1.bin`. It is a deterministic test fixture with an
`ROUTER-FIRMWARE-UNFLASHABLE` header, **not** a TP-Link image and must never be
flashed. `make image` remains the only route to a real image and stays blocked
until device and partition verification are completed.

Pushing a `v*` tag runs the same command in GitHub Actions and publishes this
fixture with `ax23v-v1.manifest.json`, `SHA256SUMS`, and `provenance.json` as
release assets. The manifest declares `flashable: false`; consumers must reject
it for installation and may use it only for backend integration testing.

`make test` exercises the safety gates. `make fetch`, `make build`, and later
stages are intentionally blocked for AX23V until every source record is locked
with an exact archive URL, immutable revision, and SHA-256 digest.

## Source locks and build recipes

Each `sources/*.yaml` is the single source record for one upstream component.
Only `status: locked` records may enter the downloader; changing a revision,
archive, or digest is a reviewable source update. The initial records name the
primary upstream but are marked `pending-verification`, rather than inventing
checksums or claiming board compatibility that has not been demonstrated.

The executable `packages/*/build` files establish the package-build boundary.
They deliberately stop before producing output until the target architecture,
cross toolchain, ABI, and source locks are known. This is intentional: a
successful command must never be mistaken for a usable AX23V firmware build.

`devices/ax23v-v1/partitions.yaml` has no inferred geometry and
`image/layouts/ax23v-v1.sh` is an explicit refusal gate. Both are replaced only
from documented stock-image and bootloader evidence, with a review that proves
the preserve list cannot be written.

The pipeline is implemented as `fetch → build → rootfs → image → attest`.
Each stage validates its inputs before proceeding:

- `fetch` downloads only HTTPS archives with a pinned SHA-256.
- `build` runs executable, repository-owned `packages/*/build` recipes with a
  controlled build environment.
- `rootfs` composes `rootfs/` and the device overlay into `build/<device>/`.
- `image` additionally requires `status: supported`, a verified partition map,
  and an executable `image/layouts/<device>.sh` layout definition.
- `attest` emits the release manifest, checksums, and source provenance.

AX23V remains in discovery until its board support, source revisions, partition
map, and signed-image format are verified. Consequently, only `make verify`
can succeed for this target today; later stages fail closed without downloading
or producing a firmware image.

## Repository boundary

- `router-firmware`: creates and attests firmware artifacts.
- `routerctl`: fetches manifests/releases and operates compatible devices; it
  contains no kernel or rootfs build logic.

Artifacts, when enabled, are written to `dist/` with a manifest, checksums, and
provenance record. No release artifact may contain preserved device data.
