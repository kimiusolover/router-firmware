# x86_64 QEMU/OVMF preview boundary

`x86_64-qemu-uefi-preview` is a separate, virtual-only target. It is not an
AX23V variant and does not establish compatibility with physical PCs.

The intended future artifact is `routeros-x86_64-uefi-preview.img`. Milestone 0
is limited to UEFI boot and login through the serial console. Before it may be
created, the x86_64 toolchain and sources must be locked, and a reproducible
GPT/ESP/root filesystem layout must be implemented. `run-qemu` is serial-only
(`-display none`, `-serial stdio`) and fixes both virtual NICs to `e1000e`;
they are reserved for the next, separate E2E milestone.

The repository currently refuses image assembly. Once a verified image and its
strict QEMU metadata exist, `make run-qemu DEVICE=x86_64-qemu-uefi-preview`
creates a copy-on-write overlay in `build/` and prints the launch command.
It never accepts a physical disk path. `make run-qemu
DEVICE=x86_64-qemu-uefi-preview QEMU_ARGS=--execute` is required to start QEMU.

Do not publish this target under the existing `v*` fixture release workflow.
That workflow publishes only the unflashable AX23V integration fixture. A
dedicated preview release gate must require serial boot/login evidence first,
then two-NIC DHCP/DNS/NAT/firewall E2E evidence, and retain the QEMU-only scope
in its release notes. Update, rollback, Wi-Fi, Secure Boot, Web UI, physical-PC
boot, and USB boot are out of scope.
