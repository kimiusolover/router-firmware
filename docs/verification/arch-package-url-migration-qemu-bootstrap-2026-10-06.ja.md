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

## 追加検証結果（2026-10-06、main / e818aeb）

### 実行環境

- OS: Arch Linux
- Branch: `main`
- Firmware checkout: `e818aeb644e5d19c71935633d51c7d9a9148f2b4`
- Command: `make qemu-bootstrap-test`
- Exit status: `0`

### 結果

`make qemu-bootstrap-test` は終了コード `0` で完了した。

今回の実行ログに対応する証跡は以下の2件。

| 項目 | 通常起動テスト | EFIローダー欠落テスト |
|---|---|---|
| Result | `passed` | `passed` |
| `negative_loader` | `false` | `true` |
| Image SHA256 | `d3d3b309fb25f0b3f0330fed74c8d16890181d8eb2c6982dc7e00953e88860d9` | `0850fddb088dc1388372af662577967bb4fa61af298fb4725e6ed09783c54fd4` |
| `base_unchanged` | `true` | `true` |

通常起動テストでは、コールドブート、adminログインとUID、sudoの誤パスワード拒否・正しいパスワードでのroot権限取得、sudoers検証、rootパスワードログイン拒否、ゲストからの電源断を確認した。

EFIローダー欠落テストでは、ログイン画面に到達しないことを確認した。

両方の証跡で `provenance_kind=arch-binary-bootstrap`、`qemu_only=true`、`uefi=true` が記録されている。

### 証跡の場所

- 通常起動:
  `build/x86_64-qemu-uefi-preview/qemu/d3d3b309fb25f0b3f0330fed74c8d16890181d8eb2c6982dc7e00953e88860d9/run-f9uthvfx/evidence.json`
- EFIローダー欠落:
  `build/x86_64-qemu-uefi-preview/qemu/0850fddb088dc1388372af662577967bb4fa61af298fb4725e6ed09783c54fd4/run-0tghd1xm/evidence.json`

### 検証範囲と制限

今回確認したのは、Arch バイナリを使用した QEMU UEFI bootstrap の起動・認証・終了、および EFI ローダー欠落時の負のテストである。

この結果は、OpenWrt 25.12.5 の実ランタイムや、RouterOS 固有のネットワーク機能の動作を検証したものではない。

なお、検証ディレクトリには過去の実行で生成された証跡も存在する。上記2件を今回の実行分として記録し、過去分とは区別する。

## 追加検証結果（2026-10-06、main / e818aeb、initramfs run/tmp 追加後）

### 実行環境

- OS: Arch Linux
- Branch: `main`
- Firmware checkout: `e818aeb644e5d19c71935633d51c7d9a9148f2b4`
- Command: `make qemu-bootstrap-test`
- Exit status: `0`
- `package_lock_sha256`: `ef0ab7593736e31f53297b462ce90f34860cd82468ce75ae254663e609b73b28`

### 結果

通常ブートテストおよび EFI ローダー欠落テストは、いずれも `passed` となった。

| 項目 | 通常ブート | EFI ローダー欠落 |
|---|---|---|
| Result | `passed` | `passed` |
| `negative_loader` | `false` | `true` |
| Image SHA-256 | `d02501f2df741c7457e50add7aee04a563a4b5ee77ff06faf2029cdf36bde008` | `3fd4f2dcfeab6cdc7333f391bfd7b1a3cc6dd676439dca0a23b46f242002d75e` |
| `base_unchanged` | `true` | `true` |

通常ブートでは、ログイン、認証、sudo 権限、sudoers 検証、root パスワードログイン拒否、およびゲストの正常終了を確認した。

EFI ローダー欠落テストでは、ログイン可能な状態に到達しないことを確認した。

両方の証跡で `provenance_kind=arch-binary-bootstrap`、`qemu_only=true`、`uefi=true` が記録されている。

通常ブートおよび EFI ローダー欠落テストのシリアルログに対して `switch_root`、`failed to mount moving /run`、`forcing unmount of /run` を検索したが、該当箇所は検出されなかった。

### 証跡の場所

- 通常ブート: `build/x86_64-qemu-uefi-preview/qemu/d02501f2df741c7457e50add7aee04a563a4b5ee77ff06faf2029cdf36bde008/run-iab5wgvy/evidence.json`
- EFI ローダー欠落: `build/x86_64-qemu-uefi-preview/qemu/3fd4f2dcfeab6cdc7333f391bfd7b1a3cc6dd676439dca0a23b46f242002d75e/run-0tlgvw3z/evidence.json`

### 検証範囲と制限

この検証は Arch バイナリを使用した QEMU UEFI bootstrap の起動・認証・終了、および EFI ローダー欠落時の負のテストを対象とする。OpenWrt 25.12.5 の実ランタイムや RouterOS 固有のネットワーク機能の動作を検証したものではない。

証跡の `firmware_checkout` は Git コミット `e818aeb644e5d19c71935633d51c7d9a9148f2b4` を示す。`scripts/preview/assemble.py` には未コミット変更があったため、コミットの識別情報だけではビルドに取り込まれた全ソース変更を特定できない。


## initramfs の `/run`・`/tmp` 作成修正後の再検証

検証日: 2026-10-06

### 変更内容

コミット `fdfa8236632639d63e2fc01025ebdea7e09d2dba` で、`scripts/preview/assemble.py` の initramfs 初期ディレクトリ作成対象に `run` と `tmp` を追加した。

### 検証環境

* Target: `x86_64-qemu-uefi-preview`
* Boot mode: UEFI
* Test environment: QEMU only
* Provenance: `arch-binary-bootstrap`
* Package lock SHA-256: `ef0ab7593736e31f53297b462ce90f34860cd82468ce75ae254663e609b73b28`
* Base unchanged: `true`

### 検証結果

通常起動テスト: **passed**

* Image SHA-256: `4408fc2a23ef2ed4197e1ad765836f9082fca6a2021e1cedf05fe43fd6023407`
* Serial SHA-256: `11c2bde7e626f6d41bb3d8af231a75b252d3926427826bde32c8f21b3059fc71`
* Evidence: `build/x86_64-qemu-uefi-preview/qemu/4408fc2a23ef2ed4197e1ad765836f9082fca6a2021e1cedf05fe43fd6023407/run-m8ay4p3w/evidence.json`
* Checks: `cold_boot_login_prompt`, `admin_password_login_uid_1000`, `sudo_wrong_password_rejected`, `sudo_correct_password_uid_0`, `target_sudoers_valid`, `root_password_login_rejected`, `guest_poweroff`

EFI ローダー欠落時の異常系テスト: **passed**

* Image SHA-256: `b5ae5494e36f1a9f240dec481de97231871ef370ea6f709351063649a519c975`
* Serial SHA-256: `dd43538d51cee3ec448878e80c4dfa248f442329b0a4dfcfdd3a7c3f206b9670`
* Evidence: `build/x86_64-qemu-uefi-preview/qemu/b5ae5494e36f1a9f240dec481de97231871ef370ea6f709351063649a519c975/run-d2gsx7wc/evidence.json`
* Check: `missing_loader_does_not_reach_login`

両テストの `firmware_checkout` は `fdfa8236632639d63e2fc01025ebdea7e09d2dba` で一致した。

### 判定と制限事項

今回の QEMU UEFI プレビュー環境では、通常起動と EFI ローダー欠落時の異常系テストがともに成功した。

この結果は QEMU 上の検証結果であり、実機の全デバイスでの動作を保証するものではない。`systemd-imds-generator` の終了コード 1 と `libbpf` 不在の警告は、別途評価する。
