SHELL := /usr/bin/env bash
DEVICE ?= ax23v-v1

.PHONY: help fetch build rootfs image sample-image attest verify plan-storage plan-tiny test clean

help:
	@printf '%s\n' 'Targets: fetch build rootfs image sample-image attest verify plan-storage plan-tiny test clean' \
	  'Set DEVICE=<target> (default: ax23v-v1).'

fetch build rootfs image attest verify plan-storage plan-tiny:
	@./scripts/$@ --device "$(DEVICE)"

sample-image:
	@./scripts/sample-image --device "$(DEVICE)"

test:
	@python3 -m unittest discover -s tests -p 'test_*.py'

clean:
	@rm -rf build
