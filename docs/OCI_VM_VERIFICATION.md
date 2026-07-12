# OCI VM作成後の動作確認

OCI Compute VMを作成した直後に、OS、cloud-init、ネットワーク、Python環境が正常か確認する。
この段階ではGoogleサービスアカウント鍵とCodex認証を配置せず、すべてのworker timerも起動しない。

## 前提

- インスタンスのライフサイクル状態が `実行中`
- インスタンス詳細にPublic IPv4が表示されている
- `receipt-ocr-public-subnet` が割り当てられている
- セキュリティ・リストで、現在の接続元グローバルIPv4 `/32` からTCP 22を許可している
- OCI作成時に登録したSSH秘密鍵がMacの `secrets/` にある

以下では、OCI Consoleに表示されたPublic IPv4を `VM_PUBLIC_IP` と表記する。

## 1. SSH秘密鍵の権限

Macで実行する。

```bash
cd /Users/k-hirata/Documents/receipt-ocr
chmod 600 secrets/receipt-ocr_ssh-key-2026-06-28.key
```

秘密鍵は `secrets/` 配下に置き、Gitへ追加しない。

## 2. SSH接続

```bash
ssh \
  -i secrets/receipt-ocr_ssh-key-2026-06-28.key \
  -o IdentitiesOnly=yes \
  opc@VM_PUBLIC_IP
```

初回接続ではホスト鍵のfingerprintを確認してから登録する。Oracle Linuxプラットフォームイメージの
標準ログインユーザーは `opc` であり、`root` や `receipt-ocr` では直接ログインしない。

### SSH接続に失敗する場合

| 症状 | 確認箇所 |
| --- | --- |
| タイムアウト | Public IPv4、Internet Gateway、`0.0.0.0/0`のルート、Ingressの接続元`/32` |
| `Permission denied (publickey)` | ユーザー名が`opc`か、秘密鍵が作成時の公開鍵と対になっているか |
| `UNPROTECTED PRIVATE KEY FILE` | 秘密鍵を`chmod 600`したか |
| `Connection refused` | インスタンスが実行中か、Oracle Cloud AgentとSSHサービスの起動をConsoleで確認 |

## 3. cloud-initの完了確認

以降はSSH接続したVM内で実行する。

```bash
sudo cloud-init status --wait
sudo cloud-init status --long
```

正常時は `status: done` と表示される。完了マーカーと専用ログも確認する。

```bash
sudo test -f /var/lib/receipt-ocr-poc/bootstrap-complete \
  && echo "bootstrap OK"

sudo tail -n 100 /var/log/receipt-ocr-cloud-init.log
```

期待結果:

- `bootstrap OK` と表示される
- ログ末尾に `receipt-ocr PoC bootstrap completed` がある
- `ERROR`、`Traceback`、`Required file is missing` がない

### cloud-initが失敗した場合

```bash
sudo cloud-init status --long
sudo less /var/log/cloud-init-output.log
sudo less /var/log/receipt-ocr-cloud-init.log
```

`Required file is missing` の場合、cloud-init実行時点のGitHub `main` にPoC実装が存在しなかった可能性がある。
PoC段階ではVMを手修正せず、コードのpushを確認してVMを作り直し、構築の再現性を確認する。

## 4. VMスペックとOS

```bash
uname -m
grep '^PRETTY_NAME=' /etc/os-release
nproc
free -h
df -h /
timedatectl show --property=Timezone --value
```

期待値:

| 項目 | 期待値 |
| --- | --- |
| CPUアーキテクチャ | `aarch64` |
| OS | Oracle Linux 9 |
| CPU | `1` |
| メモリ | 約6GB |
| ディスク | `sda`が約46.6GB、`/`が約30GB、`/var/oled`が約15GB |
| タイムゾーン | `Asia/Tokyo` |

## 5. デプロイ済みコード

```bash
sudo -u receipt-ocr git -C /opt/receipt-ocr status --short --branch
sudo -u receipt-ocr git -C /opt/receipt-ocr log -1 --oneline
```

期待値:

- ブランチが `main`
- 作業ツリーがclean
- コミットがOCI PoC実装を含む `9cf23cd` 以降

`?? .cache/` だけが表示される場合は、初回pip実行時にできたキャッシュである。アプリデータではないため、
VMの動作には影響しない。`.cache/`を除外する最新の`.gitignore`へ更新すると表示されなくなる。

### ブートボリューム割当ての確認

通常版Oracle Linux 9のデフォルト50GB相当のブートボリュームは、約46.6GiBのディスクとして認識され、
ルート用LVM約29.5GBと`/var/oled`用LVM約15GBに分割される。この場合、`df -h /`が約30GBでも未割当てではない。

```bash
lsblk
df -h /
```

次の合計が一致していれば、ディスク全体が割当て済みである。

```text
sda3 約44.5GB
  = ocivolume-root 約29.5GB
  + ocivolume-oled 約15GB
```

この状態で`sudo /usr/libexec/oci-growfs -y`を実行すると、`NOCHANGE`と`Unable to expand`が表示される。
これは異常ではなく、拡張できる未割当て領域がないことを示す。今後OCI Consoleでブートボリューム自体を
50GBより大きく変更した場合にだけ、`oci-growfs`でルート領域を拡張する。

## 6. Python環境

```bash
sudo -u receipt-ocr /opt/receipt-ocr/.venv/bin/python --version

sudo -u receipt-ocr \
  /opt/receipt-ocr/.venv/bin/python -m receipt_ocr --help

sudo -u receipt-ocr \
  /opt/receipt-ocr/.venv/bin/python -m unittest discover \
  -s /opt/receipt-ocr/tests
```

期待値:

- Pythonのバージョンが表示される
- CLIヘルプに `cloud-worker` と `llm-worker` が表示される
- ユニットテストがすべて成功する

ここで実行するユニットテストはGoogle APIをモックするため、Cloud Visionの利用数を消費しない。

## 7. 外向き通信

```bash
curl -fsSI https://github.com/karaware/receipt-ocr | head -n 1

curl -fsS \
  https://www.googleapis.com/discovery/v1/apis/drive/v3/rest \
  >/dev/null && echo "Google API OK"
```

GitHubのHTTPステータス行と `Google API OK` が表示されれば、DNS、Internet Gateway、HTTPSの外向き通信は
正常である。この確認は認証済みAPIを呼ばず、Vision利用数も消費しない。

## 8. systemdの初期状態

```bash
sudo systemctl is-enabled receipt-ocr-poc.timer || true
sudo systemctl is-active receipt-ocr-poc.timer || true
sudo systemctl is-enabled receipt-ocr-llm.timer || true
sudo systemctl is-active receipt-ocr-llm.timer || true
sudo systemctl is-enabled receipt-ocr-llm-health.timer || true
sudo systemctl is-active receipt-ocr-llm-health.timer || true
sudo systemctl status receipt-ocr-poc.timer --no-pager
sudo systemctl cat receipt-ocr-poc.service
sudo systemctl cat receipt-ocr-llm.service
sudo cat /var/lib/receipt-ocr-poc/NEXT_STEPS.txt
```

認証情報を配置する前は、timerが `disabled`、`inactive` であることが正常。ここで有効化しない。

## 合格条件

次をすべて満たしたらVM基盤の確認は完了。

- SSH公開鍵認証で`opc`として接続できる
- cloud-initが`done`で完了マーカーがある
- Oracle Linux 9、aarch64、1 OCPU、約6GBメモリである
- `/opt/receipt-ocr` が期待するGitコミットでclean
- Python CLIとユニットテストが成功する
- GitHubとGoogle APIへHTTPS接続できる
- `receipt-ocr-poc.timer`、`receipt-ocr-llm.timer`、`receipt-ocr-llm-health.timer`が無効・停止状態である

## 次の作業

VM基盤の合格後、[OCI PoCワーカーの認証設定と稼働開始](OCI_POC_WORKER_ACTIVATION.md)へ進む。
設定後もすぐtimerを有効化せず、次の順で確認する。

1. `cloud-worker --poc --dry-run`
2. `cloud-worker --poc --once`
3. FirestoreのPoCジョブ、結果、利用数を確認
4. 同じDriveファイルでVisionが再実行されないことを確認
5. CodexをChatGPTで認証し、health checkと1件のLLM解析を確認
6. 3つのtimerを有効化
