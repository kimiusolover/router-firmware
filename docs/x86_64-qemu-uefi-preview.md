# x86_64 QEMU/OVMF preview boundary

`x86_64-qemu-uefi-preview` is a separate, virtual-only target. It is not an
AX23V variant and does not establish compatibility with physical PCs.

The intended future artifact is `routeros-x86_64-uefi-preview.img`. Milestone 0
is limited to UEFI boot and login through the serial console. Before it may be
created, the x86_64 toolchain and sources must be locked, and a reproducible
GPT/ESP/root filesystem layout must be implemented. `run-qemu` is serial-only
(`-display none`, `-serial stdio`) and fixes both virtual NICs to `e1000e`;
they are reserved for the next, separate E2E milestone.

The guarded source-build pipeline currently refuses image assembly. An explicitly
authorized [signed binary bootstrap](qemu-binary-bootstrap.md) now provides a
separate local QEMU boot/authentication test path. Once a verified image and its
hash-bound QEMU metadata v2 exist, `make run-qemu DEVICE=x86_64-qemu-uefi-preview`
creates a fresh private base and copy-on-write overlay in `build/` and prints the launch command.
It never accepts a physical disk path. `make run-qemu
DEVICE=x86_64-qemu-uefi-preview QEMU_ARGS=--execute` is required to start QEMU.

Do not publish this target under the existing `v*` fixture release workflow.
That workflow publishes only the unflashable AX23V integration fixture. A
dedicated preview release gate must require serial boot/login evidence first,
then two-NIC DHCP/DNS/NAT/firewall E2E evidence, and retain the QEMU-only scope
in its release notes. Update, rollback, Wi-Fi, Secure Boot, Web UI, physical-PC
boot, and USB boot are out of scope.

## Milestone 0 console account

The QEMU-only overlay provisions one interactive administrator: `admin`
(uid/gid 1000), with the public test password `preview-admin`. Log in directly
as `admin`; use `sudo <command>` for individual administrative operations or
`sudo -i` for a root shell, then `exit` to leave it. Sudo requires the admin
password. There is no `preview` account, passwordless sudo, or automatic login.
The root password is locked.

The checked-in SHA-512 crypt hash uses a fixed public test salt for repeatable
staging. These credentials are exclusively for the QEMU serial preview and
must not be inherited by physical-device images. The overlay enables
`serial-getty@ttyS0`; it does not configure a remote login service.

`stage_rootfs` applies shadow mode 0600, sudoers modes 0440, and home mode 0700
without modifying host accounts. This is account/configuration staging, not a
bootable rootfs yet. Before enabling image assembly, the package composition
must provide `/bin/sh`, login with SHA-512 crypt support and its authentication
configuration, systemd's serial-getty unit, and sudo with its authentication
configuration. Final filesystem assembly must set `/etc` files to root:root
and `/home/admin` to 1000:1000; it must validate the complete target sudoers
configuration with `visudo -cf /etc/sudoers` in the assembled environment.
System/service accounts must be merged without replacing these login records.

Boot acceptance must check direct admin login, a non-root initial uid, failed
sudo authentication with an incorrect password, successful sudo authentication
with the documented password, and refusal of root password login. A login
prompt alone is not evidence that account authentication or sudo works.

The updated runner requires both `OVMF_CODE` and an `OVMF_VARS` template.
It copies both into the private run directory, keeping CODE read-only and
allowing writes only to the disposable VARS copy. Legacy metadata v1 is refused.
