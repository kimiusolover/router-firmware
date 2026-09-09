# QEMU preview pacman proposal

## Scope

This proposal applies only to `x86_64-qemu-uefi-preview`, running under the
repository's QEMU/OVMF launcher.  It does not authorize a physical-PC image,
an AX23V image, a flash operation, or use of a host block device.

`pacman` is an in-guest package manager here: it must never be used by the
firmware build host to compose the preview image.  Host-side source locks,
cross-builds, and image assembly remain the responsibility of this repository's
guarded pipeline.

## Bootstrap contract

The eventual preview rootfs must contain these target-built packages from
locked inputs:

- `pacman`, its shared-library closure, and CA certificates;
- `pacman-key` and a pinned Router OS package-signing public key;
- an initial Router OS keyring package; and
- a minimal, versioned Router OS repository database.

The source lock must record each archive's immutable revision, HTTPS origin,
exact archive name, and SHA-256.  The build must verify the exact archive it
extracts.  A host-native pacman binary or package database is never copied into
the x86_64 rootfs.

## In-guest configuration

`/etc/pacman.conf` must name only the signed Router OS preview repository by
default.  Upstream Arch repositories are disabled unless a separately reviewed
policy explicitly adds one.  `SigLevel` must require package and database
signatures; unsigned packages and unknown signing keys fail closed.

The package database, package cache, and pacman lock must be located on the
guest's writable data volume, for example:

```
/var/lib/pacman/       package database
/var/cache/pacman/pkg/ package cache
/var/lib/pacman/db.lck update lock
```

The immutable root filesystem must not be remounted writable by an update.
The preview image layout must provide and document this writable volume before
pacman is enabled.

## First boot and updates

1. The image ships with the Router OS keyring and repository database already
   verified during the image build.
2. A first-boot service initializes pacman's local trust state only if it is
   absent; it must not generate or trust a new, unpinned package-signing key.
3. `pacman -Syu` downloads only from the configured Router OS preview
   repository, verifies the repository and package signatures, checks free
   space, then installs into the writable guest volume.
4. Before a transaction, the update command creates a QEMU COW rollback point.
   A failed transaction leaves the base preview image untouched and can be
   discarded by removing that overlay.

## Required gates before enabling it

- Locked x86_64 toolchain and package source inputs.
- Reproducible GPT/ESP/rootfs/data-volume preview layout.
- A target-built pacman bootstrap package and signed Router OS repository.
- Serial-console evidence for `pacman -Q`, signature rejection, and a successful
  installation of one Router OS package in a disposable QEMU overlay.
- A rollback test proving that the pristine preview image is unchanged after a
  failed update.

Until every gate above passes, `packages.txt` deliberately does not list
`pacman`, and the guarded pipeline continues to refuse preview image assembly.

## Authorized binary-bootstrap exception

The separately authorized [QEMU binary bootstrap](qemu-binary-bootstrap.md)
uses verified Arch binary archives to validate Milestone 0 locally. The initial
dependency resolution used host pacman read-only with an empty package database;
assembly extracts locked archives without running host package-install hooks.
This exception does not activate in-guest pacman or replace the source-build
and signed Router OS repository requirements above.
