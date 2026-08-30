# AX23V storage probe

Run the probe on the AX23V after booting a known-safe system. It makes no MTD
write and does not read any MTD contents. Its output contains only partition
metadata, a small redacted storage-related kernel-log excerpt, RAM summary, and
SHA-256 digests.

```sh
scp -O scripts/storage-probe root@ROUTER:/tmp/storage-probe
ssh root@ROUTER 'chmod 700 /tmp/storage-probe && /tmp/storage-probe --output /tmp/ax23v-storage-probe'
mkdir -p ./private-evidence
scp -O -r root@ROUTER:/tmp/ax23v-storage-probe ./private-evidence/
```

Review before sharing or committing anything. The expected safe files are
`proc-mtd.txt`, `mtd-regions.tsv`, `ram-summary.txt`, `kernel-storage.txt`, and
`manifest.json`. Do not collect or commit `/dev/mtd*`, ART/factory/radio data,
`fw_printenv`, MAC addresses, serial numbers, or calibration data.

Separately capture a redacted serial boot log from power-on through U-Boot and
Linux MTD registration. Preserve its SHA-256 alongside the probe manifest.
Only after human review should these observations be used to create evidence
records and promote a capability from `observed` to `verified`.

`private-evidence/` is deliberately ignored by Git.  Do not place a copy of
this directory under another evidence directory: retain one private capture
directory per probe run and reference only its manifest and file digests from
the device capability record.
