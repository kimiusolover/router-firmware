SHELL := /usr/bin/env bash
DEVICE ?= ax23v-v1
QEMU_ARGS ?=

.PHONY: help fetch build rootfs image sample-image attest verify plan-storage plan-tiny run-qemu test clean

help:
	@printf '%s\n' 'Targets: fetch build rootfs image sample-image attest verify plan-storage plan-tiny run-qemu test clean' \
	  'QEMU binary preview: qemu-bootstrap qemu-bootstrap-run qemu-bootstrap-test' \
	  'Set DEVICE=<target> (default: ax23v-v1).'

fetch build rootfs image attest verify plan-storage plan-tiny:
	@./scripts/$@ --device "$(DEVICE)"

sample-image:
	@./scripts/sample-image --device "$(DEVICE)"

run-qemu:
	@./scripts/run-qemu --device "$(DEVICE)" $(QEMU_ARGS)

test:
	@python3 -m unittest discover -s tests -p 'test_*.py'

clean:
	@rm -rf build

# Explicitly authorized binary bootstrap; does not change source-image gates.
.PHONY: qemu-bootstrap qemu-bootstrap-run qemu-bootstrap-test
qemu-bootstrap:
	@python3 scripts/preview/prepare.py
	@unshare -Ur python3 scripts/preview/assemble.py --rebuild

qemu-bootstrap-run:
	@python3 scripts/preview/run.py $(QEMU_ARGS)

qemu-bootstrap-test:
	@python3 scripts/preview/boot_test.py --execute
	@python3 scripts/preview/boot_test.py --execute --negative-loader
