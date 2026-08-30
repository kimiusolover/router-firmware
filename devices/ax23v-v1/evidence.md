# AX23V v1 evidence register

This register separates compatibility observations from facts verified on a
specific AX23V unit.  It must not be interpreted as authorization to flash an
image; `device.yaml` remains `status: discovery`.

## Directly supported by the AX23V build report

- The AX23V report changes the AX23 v1 DTS from `gmac1 → ethphy4` to
  `gmac1 → ethphy0`, and relabels the LAN DSA ports from `0..3` to `1..4`.
  This explains the otherwise observed WAN/LAN4 reversal.
- The same report adds `{product_name:Archer AX23V,product_ver:1.0,
  special_id:4A500000}` to the SafeLoader support list.
- The original report says its 24.10.4 `sysupgrade.bin` worked; later comments
  report factory installation from stock v1.0 and an upgrade built with
  25.12.5.  These are useful field reports, not a substitute for project-owned
  test evidence.
- Initial OpenWrt configuration is wired-first: Wi-Fi was reported disabled
  until configured.

Sources: [AX23V OpenWrt report](https://www.setsuki.com/2025-10-27/ax23v-openwrt/),
[AX23V compile report](https://www.setsuki.com/2025-10-30/ax23v-openwrt-compile/).

## Inherited AX23 v1 data — pending AX23V confirmation

The upstream AX23 v1 DTS/profile is the source for MT7621 family data, 16 MiB
flash geometry, NVMEM offsets, radio EEPROM size, GPIOs, and MAC increments.
These values remain *unverified for AX23V* until a redacted device dump and
physical-port test are recorded.  In particular, this repository must not
assume that its AX23V factory/calibration partitions can be read, replaced, or
included in a produced image.

## AX23V on-device button evidence

- The physical WPS button generated OpenWrt button-hotplug events with
  `BUTTON=rfkill` for both `ACTION=pressed` and `ACTION=released`. This
  directly verifies the AX23V WPS control as GPIO 7, active-low, and `rfkill`
  in the deployed OpenWrt configuration.
- A short press of the recessed Reset control immediately closed the SSH
  connection. After reconnecting, `uptime` reported two minutes, consistent
  with a reboot caused by that press. This supports GPIO 8, active-low,
  reset-button operation and short-press reboot behavior.
- The Reset reboot cleared the temporary `/tmp` hotplug capture before it
  could be inspected. Therefore this record does not claim that the Reset
  control's hotplug name is `reset`; only its physical control and observed
  reboot behavior are verified.
- GPIO 19 is not the physical Reset control. It is the active-low external
  reset GPIO of the MT7621 PCIe controller, inherited from the MT7621 platform
  definition. It is recorded as platform data rather than AX23V-specific
  button data.

## Required project-owned validation

1. Record `/proc/mtd`, partition names and sizes, plus bootloader output.
2. Confirm WAN and all four LAN jacks through link tests.
3. Compare redacted base-MAC, interface MACs, and radio MACs; keep raw dumps
   out of version control.
4. Verify calibration offset/length and Wi-Fi bring-up on an AX23V unit.
5. Confirm the remaining LEDs, then test cold boot/reboot reliability, factory
   upgrade, sysupgrade, and recovery before changing status to `supported`.
