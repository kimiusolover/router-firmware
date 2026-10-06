# QEMU UEFI bootstrap 警告調査・修正記録

実施日: 2026-10-06
対象コミット: `0d48b0369a8ee9196fc8c63ad81a7bcda99437b0` (`0d48b03`)
作業ブランチ: `investigate-qemu-uefi-warnings`

## 1. 結論

今回の2つのメッセージは、原因が異なります。

| メッセージ | 判定 | 対処 |
|---|---|---|
| `systemd-imds-generator` の exit status `1` | **guest image の生成時不足が原因**。`systemd-imds-generator` が起動する時点で `hwdb.bin` が存在せず、generator が必要な DMI/hwdb 入力を開けない | assembly 時に、guest に含まれる hwdb source から `hwdb.bin` を生成する最小修正を実装 |
| `Neither libbpf.so.1 nor libbpf.so.0 are installed, cgroup BPF features disabled.` | **任意機能の機能制限だが、今回の image の起動・認証・sudo・終了処理には影響しない** | 修正しない。警告抑制や無関係な依存追加は行わない |

## 2. systemd-imds-generator の原因

Arch package の systemd 261.2 に含まれる generator と source を確認した。

- binary: `build/qemu-bootstrap/rootfs/usr/lib/systemd/system-generators/systemd-imds-generator`
- source: [`systemd v261 src/imds/imds-generator.c`](https://raw.githubusercontent.com/systemd/systemd/v261/src/imds/imds-generator.c)
- manual: [`systemd-imds-generator(8)`](https://www.freedesktop.org/software/systemd/man/261/systemd-imds-generator.html)

source では、明示的な `systemd.imds=` がない場合、container 判定の後に DMI modalias を読み、`sd_hwdb` で `IMDS_VENDOR` を検索する。IMDS 非対応環境なら `IMDS not enabled, skipping generator.` として exit `0` になる。一方、hwdb を開けない、または hwdb の読み取りに失敗する場合は負の errno を返し、`DEFINE_MAIN_GENERATOR_FUNCTION` の `exit_failure_if_negative` により非ゼロ終了になる。

assembled guest rootfs を確認したところ、40 個の `.hwdb` source は存在するが、generator より前に読み込まれるべき `usr/lib/udev/hwdb.bin` が存在しなかった。

```
rootfs/usr/lib/udev/hwdb.d/40-imds.hwdb       present
rootfs/usr/lib/udev/hwdb.bin                  absent before fix
```

`systemd-hwdb-update.service` は次の順序で `sysinit.target` の前に実行されるが、これは systemd generator の実行後である。したがって、generator が hwdb を必要とする時点では遅い。

```
ConditionPathExists=|!/usr/lib/udev/hwdb.bin
Before=sysinit.target systemd-update-done.service
ExecStart=systemd-hwdb update
```

このため、QEMU のような非クラウド環境で IMDS を有効にしない場合でも、generator が hwdb を開けず exit `1` になる経路が成立する。QEMU 用 rootfs に `hwdb.bin` を build 時点で含めれば、generator は hwdb を読んで `IMDS_VENDOR` がないことを確認し、正常に skip できる。

### 修正

`scripts/preview/assemble.py` の package 展開直後に、host の `systemd-hwdb` を `--root` 付きで実行する処理を追加した。

```python
run('systemd-hwdb', '--root', dest, '--usr', 'update')
```

host tool を使う理由は、assembly は target rootfs の chroot で `/proc` を mount しておらず、guest 版 `systemd-hwdb` を chroot 内で実行すると source を正しく列挙できないためである。`--root` により入力は guest の pinned package source、出力は guest rootfs の `usr/lib/udev/hwdb.bin` になる。生成後の binary は guest systemd 261.2 で読み取れることを確認した。

生成された database:

```
build/qemu-bootstrap/rootfs/usr/lib/udev/hwdb.bin
13,737,841 bytes
```

guest systemd-hwdb による確認では、Amazon EC2 および Alibaba Cloud の IMDS mappings が読み取れた。

## 3. libbpf 警告の原因と影響

systemd v261 source の `src/shared/bpf-util.c` / `bpf-util.h` を確認した。

- source tree: [`systemd v261 src/shared`](https://github.com/systemd/systemd/tree/v261/src/shared)
- kernel background: [`libbpf overview`](https://docs.kernel.org/bpf/libbpf/libbpf_overview.html)

systemd は `libbpf.so.1`、次に `libbpf.so.0` を optional dynamic loading する。どちらもない場合、次の文言を出して cgroup BPF 機能を無効化する。

```text
Neither libbpf.so.1 nor libbpf.so.0 are installed, cgroup BPF features disabled.
```

これは systemd PID 1 の起動失敗ではなく、BPF を使う resource-control / sandbox 機能だけを利用できなくする fallback である。

今回の guest rootfs には `libbpf.so.*` がなく、systemd unit/configuration に `BPFProgram=`, `IPAddressAllow=`, `IPAddressDeny=`, `RestrictNetworkInterfaces=`, `SocketBindAllow=` などの BPF 関連設定も見つからなかった。したがって、今回確認した preview image の起動、admin login、UID、sudo の拒否・成功、sudoers、root password 拒否、guest shutdown には実害がない。

将来この image に cgroup BPF を利用する sandbox policy を追加する場合は、その時点で Arch の libbpf package と kernel capability を明示的に依存関係・検証対象にするべきである。今回は依存追加や警告隠蔽を行わない。

## 4. 再現・検証結果

### 実行できた検証

| 検証 | 結果 |
|---|---|
| systemd v261 の IMDS generator source review | PASS |
| systemd v261 の libbpf source review | PASS |
| guest rootfs の hwdb source / binary の比較 | 修正前は source のみ、修正後は binary を生成 |
| guest systemd-hwdb による IMDS mapping query | PASS |
| `git diff --check` | PASS |
| `python3 -m py_compile scripts/preview/assemble.py` | PASS |
| `make qemu-bootstrap` | PASS |
| preview image生成 | PASS、`dist/routeros-x86_64-uefi-preview.img` が存在 |

### QEMU boot test

現 sandbox は Ubuntu host で、bundled Arch QEMU を直接実行できない。最終 image に対する `make qemu-bootstrap-test` は次で停止した。

```text
QEMU_BOOTSTRAP_TEST_RC=2
qemu-system-x86_64: error while loading shared libraries:
libcapstone.so.5: cannot open shared object file: No such file or directory
```

これは guest image または今回の hwdb 修正の失敗ではなく、host 側の bundled QEMU ABI / library 環境不足である。既存の検証記録では Arch Linux host 上の同じ QEMU bootstrap test が exit `0` で完了している。

今回の sandbox では boot serial log を再取得できなかったため、元の警告そのものの guest boot 再現は未実施である。ただし、警告に対応する source-level exit path、修正前 rootfs の `hwdb.bin` 欠落、assembly 後の populated database、および guest reader の mapping query を確認した。

## 5. 起動・認証・sudo・終了処理への影響

- IMDS: Router firmware の通常起動では cloud IMDS を必要としない。修正前は generator の hwdb lookup だけが失敗しており、IMDS unit が不要な QEMU では通常起動を妨げない。ただし cloud 環境の自動検出を generator failure に依存させないため、修正を適用した。
- libbpf: 今回の unit 構成では BPF resource-control 機能を使用していないため、影響なし。
- 認証、sudo、sudoers、root password 拒否、guest shutdown: 既存の Arch 実機 QEMU verification record で PASS。今回の修正はこれらの経路を変更しない。

## 6. 変更ファイル

今回の修正候補で変更したのは次の2行を含む `scripts/preview/assemble.py` のみである。

- package version / lock / SHA256 / signer は変更していない。
- `prepare.py`、GPG verification、keyring/dearmor logic は変更していない。
- libbpf 警告を隠すための logging 抑制は行っていない。

## 7. 残る事項

1. Arch Linux host または Arch-based CI runner 上で、修正後 image を用いた `make qemu-bootstrap-test` を再実行し、serial log から `systemd-imds-generator` の exit 1 が消えたことを直接確認する。
2. その serial log で libbpf 警告が残ることを確認する。残っていても、現時点では optional cgroup BPF fallback として許容する。
3. OpenWrt 実機のネットワーク機能や RouterOS 固有機能は、この QEMU test の範囲外である。
