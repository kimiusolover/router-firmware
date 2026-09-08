# QEMU Milestone 0: signed binary bootstrap

This opt-in path uses pinned Arch Linux x86_64 binary packages to test the real
UEFI → Linux → systemd → serial login → sudo chain. It was authorized separately
from the unfinished source-build pipeline. It is not a Router OS source-built
release, a signed Router OS package repository, or physical-device support.
`make image` and platform `discovery`/`unverified` gates remain unchanged.

## Build and run

Run from the router-firmware checkout on an ABI-compatible Arch Linux x86_64
build host. Required host tools include Python 3, bsdtar, GnuPG with the Arch
keyring, curl (downloads only), util-linux (unshare/modprobe), kmod, GNU cpio,
coreutils, and e2fsprogs. Unprivileged user namespaces must be enabled. QEMU and
OVMF are extracted into `build/qemu-bootstrap/tools`, not installed on the host.
QEMU's additional shared libraries still depend on the compatible build host;
this tool directory is not a portable SDK. KVM is not required: tests use TCG.

```sh
# Only needed for missing cached packages; retrieves pinned archives/signatures.
python3 scripts/preview/prepare.py --fetch
# Offline verification plus assembly. Previous staging trees are retained.
make qemu-bootstrap
# Prepare only; no VM starts.
make qemu-bootstrap-run
# Interactive serial console; no virtual NICs.
make qemu-bootstrap-run QEMU_ARGS=--execute
# Automated positive boot/authentication and missing-loader negative boot.
make qemu-bootstrap-test
```

The image is `dist/routeros-x86_64-uefi-preview.img`. Log in as `admin` with
`preview-admin`; use password-authenticated `sudo`. Shut down with
`sudo systemctl poweroff`. Root password login is locked. No `preview` account
is added. These public credentials are only for this virtual test image.
Each run starts from the pristine image: changes in an earlier overlay are not
retained in later runs. Old run directories and failed build trees remain for
inspection and can consume disk space.

## Inputs and composition

`scripts/preview/packages.lock.json` pins package name, version, exact filename,
HTTPS retrieval URL, SHA-256, signing fingerprint, and guest/host role.
Preparation verifies every archive's digest and detached signature before
extracting tools. Assembly verifies the archives again before extracting the
guest. No package install hooks run on the host and no host account files or
installed host executables are copied into the guest. Package system accounts
are preserved while the preview administrator is added; uid/gid collisions fail.

The host package manager was used read-only to resolve the initial dependency
list against an empty package database. Rebuilds use the checked-in lock, without
querying live repositories. This is an explicit exception for the binary
bootstrap to the earlier source-only pacman proposal; it does not enable
in-guest pacman or a Router OS package-signing key/repository. The guest package
inventory is `/usr/share/routeros/binary-packages.json`.

## Disk and boot contract

| Partition | Start sector | End sector | Size | Type |
|---|---:|---:|---:|---|
| ESP | 2048 | 133119 | 64 MiB | EFI System / FAT32 |
| root | 133120 | 2095103 | 958 MiB | Linux filesystem / ext4 |

Disk size is 1 GiB, sectors are 512 bytes, and the final 1 MiB contains backup
GPT space. Disk/partition GUIDs and ext4 UUID are UUIDv5 values from a fixed
namespace, device, layout ID `qemu-uefi-gpt-v1`, and region name. The FAT volume
ID is fixed. GPT creation writes a regular image file; no loop device, mount,
host block device, or host UEFI variable is used.

The ESP contains `EFI/BOOT/BOOTX64.EFI` (systemd-boot), `vmlinuz-linux`,
`initramfs.cpio`, and `loader/entries/routeros.conf`. This bootstrap deliberately
uses separate kernel/initramfs files, not the proposed future UKI. ESP payload
above 60 MiB is rejected. The initramfs checks the expected PARTUUID of the
runner's fixed virtio disk partition `/dev/vda2` before mounting ext4 and handing
over to systemd. The pinned kernel must report virtio_pci, virtio_blk, and ext4
as built-in; a changed kernel needing loadable drivers is rejected. EFI and
8250 serial console support are exercised by the boot test. The console command
line is `console=ttyS0,115200n8` and the serial getty is enabled.

Root is writable only through the per-run qcow2 overlay. Accounts/configuration
are root-owned, sudo remains setuid-root, `/home/admin` is uid/gid 1000 and mode
0700, shadow is 0600 and sudoers files are 0440. The admin password-change date
is fixed and nonzero to avoid forcing a password reset at first login.

## Isolation and evidence

QEMU metadata v2 binds the actual image SHA-256/length, layout, console, and
binary package lock digest. Legacy v1 metadata is rejected. Each launch creates
a fresh run directory, private base copy (verified after copying), qcow2 overlay,
read-only OVMF CODE copy, and writable disposable OVMF VARS copy. This prevents
stale overlay reuse and concurrent base rebuilds from changing the running VM.
The Milestone 0 launcher disables NICs and the QEMU monitor.

`build/.../qemu/<hash>-<unique>/evidence.json` records pass/fail, actual launch
arguments, QEMU version, firmware hashes, image identity, checks, and serial log
SHA-256. `source_lock_commit` is explicitly null because these are upstream
binary packages; the package lock digest identifies the actual inputs. The
firmware checkout commit alone does not describe uncommitted working-tree code.

Positive acceptance requires direct admin password login, uid 1000, rejection
of one wrong sudo password followed by correct-password sudo yielding uid 0, target
visudo validation, root password login rejection, and clean guest shutdown.
The test uses one wrong password to preserve the upstream PAM policy that
locks accounts after three consecutive failures. The negative test removes the fallback EFI loader in a separate image copy,
requires firmware failure/shell output, then checks that no login prompt appears
for 45 seconds. Boot panic, early QEMU exit and timeout fail acceptance.

`build/qemu-bootstrap/assembly.json` records GPT, ESP hashes, kernel version and
command line. Timestamps and GUIDs are partially normalized; **whole-image bit
reproducibility has not been established**. Filesystem build tools/timestamps,
rootfs minimization, source-built package closure, UKI, and release signing
remain separate follow-up work. No networking or physical-device E2E is claimed.
