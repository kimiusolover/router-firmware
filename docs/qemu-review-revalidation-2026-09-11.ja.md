# QEMU Milestone 0 レビュー残件と再検証（2026-09-11）

[English translation](qemu-review-revalidation-2026-09-11.en.md)

対象：[Issue #22 の設計レビュー](https://github.com/kimiusolover/router-firmware/issues/22#issuecomment-5574759446)。
検証対象コミット：`6f129d41408896ccef8ff0bcb2587823371678dc`。
試験開始時の作業ツリーはクリーン。完全SHAによるセッション保存先分離は、このコミットに含まれる。

既存のArchバイナリbootstrap画像を現在の起動・試験コードで再検証する。
今回、画像の再組み立て、パッケージ署名の再検証、全画像の再現性試験は行わない。

## レビュー項目の対応状況

| 項目 | 実装・確認状況 | 残件・完了条件 |
|---|---|---|
| 古いCOW再利用 | `preview_vm.py::fresh_storage` が完全SHAの下に毎回新しいセッション・検証済みbaseコピー・overlayを作成 | 画像変更、同一画像の再実行、旧セッション保持は単体テストで検証。今回のVM試験でも現行コードの起動成功を確認 |
| metadata v2 | 実画像のSHA・サイズ・layout・consoleを検証し不一致を拒否 | source-lock commitは未充足。bootstrapはpackage lock digestを記録する |
| OVMF VARS | CODE/VARSを実行ごとにコピーし、CODEは読み取り専用、VARSは使い捨て | ホストの変数領域を書き換えない仮想環境の契約を維持 |
| GPT/ESP/rootfs | `preview/assemble.py` に1 GiB GPT、64 MiB FAT32 ESP、958 MiB ext4、固定GUID、systemd-bootを実装。保存済みassembly.jsonにGPTとESPファイルのハッシュあり | 固定条件での再組み立て比較、fstab・serial-gettyの画像に結び付いたハッシュ証拠を追加する。全画像のビット再現性は未確立 |
| kernel/driver | 固定バイナリkernelのvirtio_pci・virtio_blk・ext4組込みを組み立て時に確認。EFI・serialは起動試験で確認 | source-build用kernel.configはコメントのみ。必要configを固定し、組み立て前に検証する作業が残る |
| baseの場所 | dist直下の通常ファイルに限定、シンボリックリンク拒否、コピー後にSHAを再検証 | hardlink拒否は未実装。レビューでは追加の隔離強化案であり、必須化するなら別途契約・テストを追加する |
| 自動証拠収集 | `make qemu-bootstrap-test` がtimeout付き正常系・欠落loader異常系とevidence.jsonを生成 | 対話用 `qemu-bootstrap-run --execute` 自体は証拠を生成しない。受入試験にはtestを使用する |
| 画像とmetadataの公開 | 個別の一時ファイルを順にrenameし、起動時に不一致を拒否 | 2ファイル一組としてのatomic公開は未実装。世代ディレクトリと単一参照の切替等を実装・障害試験する |

## 受入条件の差と次の判断

レビュー本文はネットワークE2Eを後段に分けている。一方、
`docs/community/qemu-preview-milestone-0.md` の既存受入条件には二つのe1000e NICと
source-lock commitが記載されている。現在のbootstrapはNICなし、source_lock_commitはnull。
また、証拠はOVMFのパス・ハッシュを持つが、OVMFバージョン専用フィールドはない。

したがって、bootstrapの起動実証と元のMilestone全条件の達成を区別する。
正式受入前に、bootstrapを独立した受入対象にするか、元の条件まで実装するかを文書とレビューで揃える。
この記録だけで元の条件を変更したり、Milestone完了・再レビュー承認を宣言したりしない。
二NIC DHCP/DNS/NAT/firewall、更新・復旧、AX23V実機は別の検証対象。

## 今回の再検証結果

- `make test`：20件成功。
- `make qemu-bootstrap-test`：正常終了（exit 0）。正常系・異常系とも `result: passed`。
- 正常系：コールドブート、adminのUID 1000、sudo誤パスワード拒否・正しいパスワードでUID 0、sudoers検証、rootパスワードログイン拒否、正常シャットダウン。
- 異常系：別コピーのEFI loaderを削除し、ファームウェアの失敗表示後45秒間ログインしないことを確認。
- 両試験のbase不変、保存済みserialログ・base・OVMF CODE・VARSテンプレートのSHAを試験後に再照合。正常系画像と現行package lockのSHAもmetadataと一致。
- 試験後の変更はこの記録と既存検証記録へのリンクのみ。実装コードの変更なし。

| 証拠 | ローカルファイル |
|---|---|
| 正常系 | [evidence.json](../build/x86_64-qemu-uefi-preview/qemu/6e8f1506a149a4e834c1f4f009e82767006335a239a07cee87aa715f8af3619e/run-cbu6ox7q/evidence.json) |
| 異常系 | [evidence.json](../build/x86_64-qemu-uefi-preview/qemu/182b793df8dd6550320b888d1c294b3be5cf407ab9afb9e61526335e2545da5a/run-mgl13k7q/evidence.json) |

正常系の画像SHAは `6e8f1506a149a4e834c1f4f009e82767006335a239a07cee87aa715f8af3619e`。
両証拠の `firmware_checkout` は冒頭の検証対象コミットと一致する。

証拠と画像はローカル生成物で、Gitには含まれない。
今回の作業はローカル検証であり、hosted CI・公開・外部レビュー承認を含まない。
