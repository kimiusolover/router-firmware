# x86_64 QEMU/OVMF preview boundary

`x86_64-qemu-uefi-preview` is a separate, virtual-only target. It is not an
AX23V variant and does not establish compatibility with physical PCs.

The intended future artifact is `routeros-x86_64-uefi-preview.img`. Before it
may be created, the x86_64 toolchain and sources must be locked, a reproducible
GPT/ESP/root filesystem layout must be implemented, and QEMU E2E evidence must
cover UEFI boot, two virtual NICs, DHCP, DNS, NAT/firewall, update, and rollback.

The repository currently refuses image assembly. Once a verified image and its
strict QEMU metadata exist, `make run-qemu DEVICE=x86_64-qemu-uefi-preview`
creates a copy-on-write overlay in `build/` and prints the launch command.
It never accepts a physical disk path. `make run-qemu
DEVICE=x86_64-qemu-uefi-preview QEMU_ARGS=--execute` is required to start QEMU.

Do not publish this target under the existing `v*` fixture release workflow.
That workflow publishes only the unflashable AX23V integration fixture. A
dedicated preview release gate must require the above E2E evidence and retain
the QEMU-only scope in its release notes.
