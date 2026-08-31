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
make plan-tiny DEVICE=ax23v-v1
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
fixture with `ax23v-v1.manifest.json`, a CycloneDX 1.5 SBOM, `SHA256SUMS`, and
`provenance.json` as release assets. The fixture, manifest, and SBOM are
keylessly signed with Sigstore and their bundles are released beside them. The
manifest declares `flashable: false`; consumers must reject
it for installation and may use it only for backend integration testing.
The workflow runs `routerctl verify-release` before publication. Its
provenance is an unsigned in-toto Statement for metadata agreement only; the
released manifest and SBOM must additionally be verified against their Sigstore
bundles before relying on the metadata.
Its backward-compatible predicate metadata also records the generator,
automation actor, AI assistance, and whether human review was required and who
performed it when those facts are supplied by the release environment.

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

## Tiny package policy

`tiny/<package>/features.yaml` is a reusable, machine-readable policy layer
for systemd, Kea, Unbound, hostapd, and Jool. It uses the common
`required` / `conditional` / `excluded` / `upstream-required` classification
and never contains upstream source copies. `make plan-tiny DEVICE=ax23v-v1`
combines that policy with device capabilities, an optional certification
profile, and an optional deployment policy to write `build/<device>/tiny.plan.json`.
Missing, unset, or non-true requirements leave a conditional feature out.

The AX23V capability input deliberately leaves VHT, HE, and mesh unset; the
planner must not infer them from AX23 v1. The output is only a proposed build
profile (including systemd binary and unit allowlists), never authorization to
build, transmit, flash, or release an image. The formal contract is
`docs/tiny-planner-specification.yaml`; the per-package policy schema is
`schemas/tiny-features.schema.json`.

## AX23V compatibility record

`devices/ax23v-v1/hardware-overlay.yaml` captures the currently evidenced
AX23V delta from the upstream Archer AX23 v1 profile without enabling image
assembly.  The relevant difference is physical Ethernet wiring: AX23V uses
GMAC1/PHY0 for WAN and DSA ports 1–4 for LAN1–LAN4.  The overlay also records
the observed AX23V SafeLoader support-list identity.  Inherited NVMEM, radio,
GPIO, MAC, and partition information remains explicitly marked for on-device
verification.  See `devices/ax23v-v1/evidence.md` for sources and the required
validation sequence.

## Repository boundary

- `router-firmware`: creates and attests firmware artifacts.
- `routerctl`: fetches manifests/releases and operates compatible devices; it
  contains no kernel or rootfs build logic.

Artifacts, when enabled, are written to `dist/` with a schema-v2 manifest,
checksums, and provenance record. Every manifest artifact records its name,
SHA-256, byte size, and format; `board_id` is emitted only when directly known.
The allowed formats are `tplink-safeloader`, `openwrt-sysupgrade`, and
`router-firmware-unflashable-fixture`. No release artifact may contain
preserved device data.
