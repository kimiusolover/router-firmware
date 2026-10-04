# QEMU Milestone 0 review follow-up and revalidation (2026-09-11)

English translation of the [Japanese revalidation record](qemu-review-revalidation-2026-09-11.ja.md). The results below describe that validation run; this translation does not report a new test run.

Review: [Issue #22 design review](https://github.com/kimiusolover/router-firmware/issues/22#issuecomment-5574759446).
Commit under test: `6f129d41408896ccef8ff0bcb2587823371678dc`.
The working tree was clean when testing began. This commit includes session storage isolation using the full image SHA-256.

The existing Arch binary bootstrap image was revalidated using the current launch and test code.
This run did not rebuild the image, reverify package signatures, or test whole-image reproducibility.

## Response to review findings

| Finding | Implementation and verification | Remaining work / completion criteria |
|---|---|---|
| Stale COW reuse | `preview_vm.py::fresh_storage` creates a fresh session, verified private base copy, and overlay under the full image SHA-256 on every run | Unit tests cover changed images, repeated runs of the same image, and preservation of older sessions. This VM run also confirmed successful boot with the current code. |
| Metadata v2 | Validates the actual image SHA-256, size, layout, and console; rejects mismatches | The source-lock commit requirement remains unmet. The bootstrap records a package lock digest. |
| OVMF VARS | Copies CODE/VARS for each run; CODE is read-only and VARS is disposable | Preserves the virtual-environment contract that host firmware variable storage must not be modified. |
| GPT/ESP/rootfs | `preview/assemble.py` implements a 1 GiB GPT image, 64 MiB FAT32 ESP, 958 MiB ext4 root, fixed GUIDs, and systemd-boot. The saved `assembly.json` contains GPT and ESP file hashes. | Compare rebuilds under fixed conditions and add image-bound hash evidence for fstab and serial-getty. Whole-image bit reproducibility has not been established. |
| Kernel/driver | Assembly checks that virtio_pci, virtio_blk, and ext4 are built into the pinned binary kernel. Boot tests exercise EFI and serial support. | The source-build `kernel.config` contains comments only. Required configuration must still be pinned and verified before assembly. |
| Base location | Restricts inputs to regular files directly in `dist/`, rejects symlinks, and rechecks SHA-256 after copying | Hardlink rejection is not implemented. The review presents it as optional isolation hardening; making it mandatory would require a separate contract and tests. |
| Automated evidence collection | `make qemu-bootstrap-test` runs timeout-bounded positive and missing-loader negative tests and generates `evidence.json` | Interactive `qemu-bootstrap-run --execute` does not itself generate evidence. Use the test target for acceptance testing. |
| Image and metadata publication | Renames individual temporary files in sequence and rejects mismatches at launch | Atomic publication of the two files as a pair is not implemented. Implement and fault-test a mechanism such as generation directories with a single reference switch. |

## Acceptance differences and next decision

The review defers network E2E to a later stage. However, the existing acceptance criteria in
`docs/community/qemu-preview-milestone-0.md` specify two e1000e NICs and a source-lock commit.
The current bootstrap has no NICs, and `source_lock_commit` is null.
The evidence also contains OVMF paths and hashes, but no dedicated OVMF version field.

Successful bootstrap boot validation and satisfaction of all original milestone criteria are therefore separate results.
Before formal acceptance, the documentation and review must agree whether to accept the bootstrap separately or implement the original criteria in full.
This record does not change those criteria or declare milestone completion or follow-up review approval.
Two-NIC DHCP/DNS/NAT/firewall, update/recovery, and AX23V hardware require separate validation.

## Revalidation results

- `make test`: all 20 tests passed.
- `make qemu-bootstrap-test`: completed successfully (exit 0). Both positive and negative tests reported `result: passed`.
- Positive test: cold boot, admin UID 1000, rejection of an incorrect sudo password, UID 0 with the correct sudo password, sudoers validation, rejection of root password login, and clean shutdown.
- Negative test: removed the EFI loader from a separate image copy and confirmed that no login prompt appeared for 45 seconds after firmware failure output.
- Confirmed that both test base images remained unchanged. After testing, rechecked the SHA-256 hashes of the saved serial logs, base images, OVMF CODE, and VARS template. The positive-test image and current package lock hashes also matched the metadata.
- Changes after testing were limited to this record and a link from the existing validation record. No implementation code changed.

| Evidence | Local file |
|---|---|
| Positive test | [evidence.json](../build/x86_64-qemu-uefi-preview/qemu/6e8f1506a149a4e834c1f4f009e82767006335a239a07cee87aa715f8af3619e/run-cbu6ox7q/evidence.json) |
| Negative test | [evidence.json](../build/x86_64-qemu-uefi-preview/qemu/182b793df8dd6550320b888d1c294b3be5cf407ab9afb9e61526335e2545da5a/run-mgl13k7q/evidence.json) |

The positive-test image SHA-256 is `6e8f1506a149a4e834c1f4f009e82767006335a239a07cee87aa715f8af3619e`.
The `firmware_checkout` in both evidence records matches the commit under test listed above.

The evidence and images are locally generated artifacts and are not included in Git. The local evidence links above are retained from the Japanese record and are not accessible through GitHub.
This was local validation; it did not include hosted CI, publication, or external review approval.
