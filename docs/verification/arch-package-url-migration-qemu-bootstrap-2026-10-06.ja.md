# Arch package URL 一括保守・QEMU bootstrap 最終報告

実施日: 2026-10-06

## 結論

- `packages.lock.json` の artifact identity（package name / version / filename / SHA256 / signer fingerprint）は変更していません。
- repository の変更は **14 entry の `url` フィールドだけ**です。
- 現在残っている 70 件の locked mirror URL を事前に検査した結果、HTTP 404 は **0 件**でした。404 以外の URL を Archive へ自動切替していません。
- `prepare.py --fetch` は成功しました。
- `make qemu-bootstrap` は成功し、preview image を生成しました。
- `make qemu-bootstrap-test` は、Arch の bundled QEMU が Ubuntu 24.04 host の glibc / shared-library ABI と一致しないため失敗しました。repository code や lock metadata の問題ではありません。
- commit / push は実施していません。

## 1. Archive へ変更した package 一覧

| package | version | SHA256 | signer fingerprint | 変更前 URL | 変更後 URL |
|---|---|---|---|---|---|
| tzdata | 2026c-1 | `3be0345f3a9393f30b5e1167ab4593f55c75031daa123526a581b975d45ec5e3` | `ADC8A1FCC15E01D45310419E94657AB20F2A092B` | `https://mirrors.cat.net/archlinux/core/os/x86_64/tzdata-2026c-1-x86_64.pkg.tar.zst` | `https://archive.archlinux.org/packages/t/tzdata/tzdata-2026c-1-x86_64.pkg.tar.zst` |
| glibc | 2.44+r24+g16be1518495f-1 | `5db2283f5b46b6114d06b4bc71fcf8ede5f1a04fcccb4d307048fcdc4e501d93` | `05C7775A9E8B977407FE08E69D4C5AA15426DA0A` | `https://mirrors.cat.net/archlinux/core/os/x86_64/glibc-2.44+r24+g16be1518495f-1-x86_64.pkg.tar.zst` | `https://archive.archlinux.org/packages/g/glibc/glibc-2.44+r24+g16be1518495f-1-x86_64.pkg.tar.zst` |
| readline | 8.3.003-1 | `a4e861378069dcb15c6fbd52a1f5d9ed01b4bce5fb208268c7c182341f5f3960` | `5B7E3FB71B7F10329A1C03AB771DF6627EDF681F` | `https://mirrors.cat.net/archlinux/core/os/x86_64/readline-8.3.003-1-x86_64.pkg.tar.zst` | `https://archive.archlinux.org/packages/r/readline/readline-8.3.003-1-x86_64.pkg.tar.zst` |
| xz | 5.8.3-1 | `03b9eefeb02c27c4f30fce4481cb5bd2922c0391f628665911c156970285d5d9` | `0429897DE5F3BDAC537A30696D42BDD116E0068F` | `https://mirrors.cat.net/archlinux/core/os/x86_64/xz-5.8.3-1-x86_64.pkg.tar.zst` | `https://archive.archlinux.org/packages/x/xz/xz-5.8.3-1-x86_64.pkg.tar.zst` |
| libldap | 2.6.13-1 | `9d37ed49d0da014fbdf89e8b1c5e55b2d58fbffc850d79ddda5f8d1d151ba3b6` | `05C7775A9E8B977407FE08E69D4C5AA15426DA0A` | `https://mirrors.cat.net/archlinux/core/os/x86_64/libldap-2.6.13-1-x86_64.pkg.tar.zst` | `https://archive.archlinux.org/packages/l/libldap/libldap-2.6.13-1-x86_64.pkg.tar.zst` |
| libtirpc | 1.3.7-1 | `2d43a2bab8dbe99fa817d327bdf23ec559a337ebd25b48c691cff73f3eb138ec` | `ADC8A1FCC15E01D45310419E94657AB20F2A092B` | `https://mirrors.cat.net/archlinux/core/os/x86_64/libtirpc-1.3.7-1-x86_64.pkg.tar.zst` | `https://archive.archlinux.org/packages/l/libtirpc/libtirpc-1.3.7-1-x86_64.pkg.tar.zst` |
| systemd-libs | 261.2-1 | `c12d5a2c4bb7cc0088af3f6addddac3219277a14b4aefb135b508d6d9ea15de9` | `0429897DE5F3BDAC537A30696D42BDD116E0068F` | `https://mirrors.cat.net/archlinux/core/os/x86_64/systemd-libs-261.2-1-x86_64.pkg.tar.zst` | `https://archive.archlinux.org/packages/s/systemd/systemd-libs-261.2-1-x86_64.pkg.tar.zst` |
| pam | 1.7.2-2 | `49f54d6b632d0e83cde032eb01f903b71ac09e7dc9bbafbd64fea70227337d48` | `5B7E3FB71B7F10329A1C03AB771DF6627EDF681F` | `https://mirrors.cat.net/archlinux/core/os/x86_64/pam-1.7.2-2-x86_64.pkg.tar.zst` | `https://archive.archlinux.org/packages/p/pam/pam-1.7.2-2-x86_64.pkg.tar.zst` |
| coreutils | 9.11-2 | `8d6668fba51085e680b1510f16ff43d32fbfdd068e78b2000783a4dab1c15513` | `5B7E3FB71B7F10329A1C03AB771DF6627EDF681F` | `https://mirrors.cat.net/archlinux/core/os/x86_64/coreutils-9.11-2-x86_64.pkg.tar.zst` | `https://archive.archlinux.org/packages/c/coreutils/coreutils-9.11-2-x86_64.pkg.tar.zst` |
| device-mapper | 2.03.42-1 | `823b3ae9d616defbd61dbc7cf92f489b996ce520de54a2bbea8ced0918c069c3` | `0429897DE5F3BDAC537A30696D42BDD116E0068F` | `https://mirrors.cat.net/archlinux/core/os/x86_64/device-mapper-2.03.42-1-x86_64.pkg.tar.zst` | `https://archive.archlinux.org/packages/d/device-mapper/device-mapper-2.03.42-1-x86_64.pkg.tar.zst` |
| cryptsetup | 2.8.7-1 | `3e77b353731dd4432a7b451fca4b6880b89405c5914324b82a294f3c5fd75393` | `0429897DE5F3BDAC537A30696D42BDD116E0068F` | `https://mirrors.cat.net/archlinux/core/os/x86_64/cryptsetup-2.8.7-1-x86_64.pkg.tar.zst` | `https://archive.archlinux.org/packages/c/cryptsetup/cryptsetup-2.8.7-1-x86_64.pkg.tar.zst` |
| hwdata | 0.410-1 | `7fdb0f7f95bca493778d939f3a47580fb950a3c827aba337ca34412c672be083` | `5B7E3FB71B7F10329A1C03AB771DF6627EDF681F` | `https://mirrors.cat.net/archlinux/core/os/x86_64/hwdata-0.410-1-any.pkg.tar.zst` | `https://archive.archlinux.org/packages/h/hwdata/hwdata-0.410-1-any.pkg.tar.zst` |
| leancrypto | 1.8.0-1 | `5b793364a382b3f46857ce5ed96cde520466aeec5443cad04339f76078ab6589` | `ADC8A1FCC15E01D45310419E94657AB20F2A092B` | `https://mirrors.cat.net/archlinux/core/os/x86_64/leancrypto-1.8.0-1-x86_64.pkg.tar.zst` | `https://archive.archlinux.org/packages/l/leancrypto/leancrypto-1.8.0-1-x86_64.pkg.tar.zst` |
| mkinitcpio | 41.1-1 | `5c9e79eaef65036a1bfe675f3726bd1a7d8f8e4ad9f82e7be15ba2efe2250ef9` | `2E36D8620221482FC45CB7F2A91764759326B440` | `https://mirrors.cat.net/archlinux/core/os/x86_64/mkinitcpio-41.1-1-any.pkg.tar.zst` | `https://archive.archlinux.org/packages/m/mkinitcpio/mkinitcpio-41.1-1-any.pkg.tar.zst` |

各 entry は package hash 一致、`.sig` 取得、`gpgv exit 0`、`GOODSIG`、`VALIDSIG`、full fingerprint 一致、package metadata 整合を確認済みです。

## 2. 一括 mirror scan

- lock entries: 116
- locked mirror URLs inspected: 70
- HTTP 404: 0
- HTTP 200: 70
- HTTP 404 以外の理由で Archive へ切替: 0

過去の個別調査で確認済みの Archive fallback 14 件だけを保持しています。

## 3. pipeline 結果

| command | result | details |
|---|---|---|
| `git diff --check` | PASS | whitespace error なし |
| `python3 scripts/preview/prepare.py --fetch` | PASS | 全 package cache の SHA256/GPG 検証と tools 展開完了 |
| `make qemu-bootstrap` | PASS | 再確認 exit 0。image と metadata 生成 |
| `make qemu-bootstrap-test` | BLOCKED / exit 2 | bundled `qemu-system-x86_64` が host の glibc 2.39 に対して `GLIBC_2.42` / `GLIBC_2.43` を要求し、さらに `libcapstone.so.5` 等の Arch runtime ABI が host にない |

途中で不足していた host tools/libraries (`bsdtar`, `depmod`, `cpio`, `libpopt0`, `liburing2`, `libcapstone4`) は repository 外の環境依存として補いました。`libcapstone4` は `.so.5` を提供しないため、test は ABI mismatch のまま停止しています。code や lock の変更はしていません。

## 4. 最終 diff / worktree

- `scripts/preview/packages.lock.json`: URL-only replacements 14 件（28 diff lines: 14 removals + 14 additions）
- version / filename / sha256 / signer_fingerprint / roles / other metadata: 未変更
- `prepare.py`, keyring/dearmor, GPG verification logic: 未変更
- `git diff --check`: PASS
- commit / push: 未実施

生成物:

- `dist/routeros-x86_64-uefi-preview.img` — 1,073,741,824 bytes
- `dist/routeros-x86_64-uefi-preview.img.qemu.json`

## 5. 次に実施すべき作業

`qemu-bootstrap-test` を完走させるには、Ubuntu host 上で無理に symlink や system library の置換を行わず、Arch Linux userspace / VM / persistent Cloud Computer など、bundled QEMU が要求する glibc 2.42+ と全 host libraries を提供する実行環境で同じ `make qemu-bootstrap-test` を再実行してください。repository の artifact lock 修正はこの時点で完了しています。

## Arch Linux 実機検証結果

検証環境:
- OS: Arch Linux
- Repository HEAD: `aa61e60` (`Merge pull request #38 from kimiusolover/feature/arch-package-archive-urls`)
- 検証日: 2026-10-06

実行結果:

```text
python3 scripts/preview/prepare.py --fetch
PASS
Pinned package cache verified; tools extracted successfully.

make qemu-bootstrap
PASS
Generated:
dist/routeros-x86_64-uefi-preview.img
dist/routeros-x86_64-uefi-preview.img.qemu.json

make qemu-bootstrap-test
PASS
qemu-bootstrap-test exit=0

QEMU bootstrap testでは複数の evidence.json が生成され、qemu-bootstrap-test は終了コード 0 で完了した。

Ubuntu 24.04環境ではQEMU実行時のGLIBC_2.42/GLIBC_2.43要求により実行できなかったが、Arch Linux環境では同じコミット上でQEMU bootstrap testを正常完了できることを確認した。

今回の検証により、Arch package Archive URL変更後のpackage cache検証、preview image生成、およびQEMU bootstrap testまでの一連の処理がArch Linux環境で正常に完了することを確認した。
