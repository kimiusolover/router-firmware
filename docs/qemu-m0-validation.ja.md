# QEMU Milestone 0 実パッケージ検証（2026-09-08）

署名とSHA-256を確認したArch Linuxのゲスト用96パッケージから、
1GiBのGPT / 64MiB FAT32 ESP / 958MiB ext4イメージを再生成した。
独自ソースビルド版やRouter OS署名済みパッケージリポジトリの完成を示すものではない。

## 起動する

```sh
cd /home/nakan/projectmain/router-firmware
make qemu-bootstrap-run QEMU_ARGS=--execute
```

シリアル端末で `admin` / `preview-admin` を入力する。
管理操作にはパスワード付き `sudo` を使う。終了は `sudo systemctl poweroff`。
毎回新しい差分ディスクを作るため、前回の変更は引き継がない。
公開テスト用アカウントであり、ネットワーク機器はQEMUに接続しない。

## 今回確認したこと

- `make qemu-bootstrap`：キャッシュした固定パッケージの署名・ハッシュ検証と再生成に成功。
- `make test`：17件成功。
- `make qemu-bootstrap-test`：新規COWと使い捨てOVMF変数領域で正常系・異常系とも成功。
- 正常系：シリアル起動、adminのUID 1000、sudoの誤パスワード拒否、正しいパスワードでUID 0、sudoers構文、rootパスワードログイン拒否、ゲスト終了。
- 異常系：別コピーのEFIローダーを削除し、OVMFの起動失敗表示後45秒間ログインプロンプトが出ないことを確認。
- 両試験でベースイメージは不変。保存したシリアルログのSHA-256も再照合済み。

試験コードは、シェルの制御文字に伴う余分なCRでUIDの表示を見落としていたため修正した。
また、sudoの誤パスワード試験は1回の拒否後に正しいパスワードを入力する。
3回連続失敗時のPAMアカウントロックは変更していない。

## 成果物と証拠

- イメージ：`dist/routeros-x86_64-uefi-preview.img`
- メタデータ：`dist/routeros-x86_64-uefi-preview.img.qemu.json`
- イメージSHA-256：`6e8f1506a149a4e834c1f4f009e82767006335a239a07cee87aa715f8af3619e`
- 正常系：[`evidence.json`](../build/x86_64-qemu-uefi-preview/qemu/6e8f1506a149a4e8-9daar6ag/evidence.json)
- 異常系：[`evidence.json`](../build/x86_64-qemu-uefi-preview/qemu/182b793df8dd6550-dik6zqdn/evidence.json)

証拠とイメージはローカル生成物で、Gitには含まれない。再生成でイメージのハッシュは変わり得る。
全イメージのビット再現性、独自パッケージ配布・更新、ネットワーク、実機起動は未検証。
既存のsource-build向けimageゲートとプラットフォームのサポート状態は維持する。
詳しい入力・配置契約は[バイナリbootstrap手順](qemu-binary-bootstrap.md)を参照。
