# GitHub Actions runner policy

This repository uses GitHub-hosted runners only. Do not add `self-hosted`
labels to workflows. Keep routine CI small; run long-running, hardware-bound,
or QEMU end-to-end checks explicitly on a local development machine.

The `runner-policy` workflow rejects `self-hosted` and `self_hosted` labels in
workflow files.
