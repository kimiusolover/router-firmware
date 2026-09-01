SHELL := /usr/bin/env bash
DEVICE ?= ax23v-v1
QEMU_ARGS ?=

.PHONY: help fetch build rootfs image sample-image attest verify plan-storage plan-tiny run-qemu test clean

help:
	@printf '%s\n' 'Targets: fetch build rootfs image sample-image attest verify plan-storage plan-tiny run-qemu test clean' \
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
