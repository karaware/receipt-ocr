# OCI Cloud Vision PoCワーカーのセットアップ

このワーカーはPoC専用コレクションだけを使用し、PoC全体を通したVision利用予約数を最大20回に制限する。

## 推奨VMスペック

PoCでは次の1台構成を使用する。

| 項目 | 選択値 | 理由 |
| --- | --- | --- |
| シェイプ | `VM.Standard.A1.Flex`（Always Free対象表示を確認） | PythonとGoogle SDKはARM64で動作し、無料枠内でメモリに余裕がある |
| OCPU | 1 | 5分ごとに最大1枚処理するPoCには十分 |
| メモリ | 6GB | Python、Vision/Drive/Firestore SDKを同時に動かしても余裕がある |
| ネットワーク | 1Gbps（シェイプ既定） | レシート画像の取得には十分 |
| ブートボリューム | 50GB、Balanced、暗号化あり | OCIのデフォルト最小構成で、リポジトリ・venv・一時画像に十分 |
| VM数 | 1台 | systemd timerで直列処理し、重複実行を避ける |
| 受信ポート | TCP 22のみ | PoCワーカーは公開HTTPサーバーを持たない |

VCN/サブネットのEgressは、OS更新、GitHub、Google API、DNS、時刻同期に必要な外向き通信を許可する。
IngressはSSHだけを接続元IP `/32` に限定する。

### ブートボリュームと推定コスト表示

OCI Consoleの「推定コストの表示」では、50GBのブートボリュームに月額費用が表示される場合がある。
これはAlways Free枠を差し引く前の参考価格であり、その表示だけで課金が確定するわけではない。

Always Freeには、ホームリージョン内のブートボリュームとブロックボリュームを合計して200GBまで含まれる。
今回の50GBブートボリュームは、次の条件をすべて満たせば無料枠内である。

- ホームリージョンのIndia West (Mumbai)に作成する
- 既存分を含むブートボリュームとブロックボリュームの合計を200GB以下にする
- ブートボリュームはデフォルトの50GBを使用する
- ボリューム・パフォーマンスはデフォルトの `Balanced` を使用する
- 暗号化はOracle管理キーを使用し、独自のVaultキーは作成しない
- PoCでは追加ブロックボリュームを作成しない

ストレージ画面では次の設定を選ぶ。

| 設定 | 選択値 |
| --- | --- |
| ブートボリューム容量 | 50GB |
| パフォーマンス | `Balanced` |
| 転送中暗号化 | 有効でよい |
| 保存時暗号化 | Oracle管理キー |
| 顧客管理キー/Vault | 使用しない |
| 追加ブロックボリューム | なし |

VM作成画面の「ストレージ」では、次の操作を行う。

1. 「カスタム・ブート・ボリューム・サイズとパフォーマンスを指定します」は **OFF** のままにする。
   画面に約46.6GBと表示される場合があるが、これはデフォルト50GB相当のブートボリュームである。
2. 「転送中暗号化の使用」は **ON** のままにする。
3. 「自分が管理するキーでこのボリュームを暗号化」は **OFF** のままにする。保存時暗号化には
   Oracle管理キーを使用するため、独自のVaultやキーを作成する必要はない。
4. 「ブロック・ボリュームのアタッチ」は押さず、追加ボリュームが「表示するアイテムがありません」の
   状態で進める。

この設定では、ブートボリュームは保存時・転送中とも暗号化され、Always Freeの200GB枠のうち約50GBを使用する。

過去に削除したVMのブートボリュームが残っている場合も200GB枠を消費する。VM作成前にOCI Consoleの
「ストレージ」→「ブロック・ストレージ」→「ブート・ボリューム」で、ホームリージョン内の合計容量を確認する。
VMを破棄するときは、不要なら関連ブートボリュームも同時に削除する。

参考: [OCI Always Freeリソース — ブロック・ボリューム](https://docs.oracle.com/ja-jp/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm#Always_Free_Resources__blockvolume)

2026年6月現在、Always FreeのAmpere A1はテナンシ全体で月1,500 OCPU時間・9,000GB時間、
常時稼働換算で合計2 OCPU・12GB相当である。PoCの1 OCPU・6GBはその半分を使用する。
作成画面と作成後のインスタンス詳細の両方で **Always Free対象** と表示されることを確認する。

スクリーンショットのホームリージョンはIndia West (Mumbai)である。Always Free Computeはホームリージョンに
作成する必要があるため、このテナンシではMumbaiへ作成する。日本からのSSH操作には遅延があるが、5分間隔の
バックグラウンドワーカーには実用上影響しない。

## OS

**通常版のOracle Linux 9の最新ARM64イメージ**を選択する。画面上では `Oracle Linux 9` を選び、
次は選ばない。

- Oracle Linux 10: Python・Google SDKとの組合せをPoCで新たに検証する必要がある
- Oracle Autonomous Linux: 自動管理機能は今回不要
- Oracle Linux 9 Minimal: 不足パッケージの切り分けが増える
- Oracle Linux Cloud Developer: PoCに不要な開発ツールが多い

Oracle Linux 9はOCI向けプラットフォームイメージとして提供され、cloud-init、標準リポジトリ、Kspliceを
利用できる。標準のログインユーザーは `opc`。PoCアプリはcloud-initが作るログイン不可の専用ユーザー
`receipt-ocr` で実行する。

参考:

- [OCI Always Free Resources](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm)
- [Oracle Linux 9 Image](https://docs.oracle.com/iaas/oracle-linux/oci/oracle-linux-9.htm)
- [OCI instance metadataとcloud-init user data](https://docs.oracle.com/en-us/iaas/Content/Compute/Tasks/gettingmetadata.htm)

## VCNの作成

PoCでは、公開サブネットを1つだけ持つ最小VCNを手動作成する。「インターネット接続性を持つVCN」
ウィザードは、今回不要なプライベートサブネットやNAT Gatewayも作成する可能性があるため使用しない。

作成するリソースは次のとおり。

```text
receipt-ocr-vcn                    10.0.0.0/16
  receipt-ocr-public-subnet        10.0.0.0/24
  receipt-ocr-igw                  Internet Gateway
  Default Route Table              0.0.0.0/0 -> receipt-ocr-igw
  Default Security List            SSHは接続元IPだけ
```

VCN、サブネット、Internet Gateway自体にVMや追加ストレージは含まれない。PoCではNAT Gateway、Load Balancer、
予約済Public IP、追加Network Security Groupを作らない。

### 1. VCN本体

OCI Consoleで「ネットワーキング」→「仮想クラウド・ネットワーク」を開き、「VCNの作成」を選択する。

| 項目 | 設定値 |
| --- | --- |
| 名前 | `receipt-ocr-vcn` |
| コンパートメント | VMと同じコンパートメント |
| IPv4 CIDRブロック | `10.0.0.0/16` |
| DNS解決 | 有効 |
| DNSラベル | `receiptocr` |
| IPv6 | 無効 |

作成後、VCN詳細画面を開く。VCN作成時にデフォルトのルート表、セキュリティ・リスト、DHCPオプションも
作成される。

### 2. Internet Gateway

VCN詳細の「ゲートウェイ」または「Internet Gateway」から作成する。

| 項目 | 設定値 |
| --- | --- |
| 名前 | `receipt-ocr-igw` |
| コンパートメント | VCNと同じ |
| 有効 | ON |
| ルート表の関連付け | 指定しない |

### 3. デフォルト・ルート表

VCN詳細の「ルーティング」→「ルート表」からデフォルト・ルート表を開き、次のルールを追加する。

| 項目 | 設定値 |
| --- | --- |
| ターゲット・タイプ | Internet Gateway |
| 宛先タイプ | CIDRブロック |
| 宛先CIDRブロック | `0.0.0.0/0` |
| ターゲット | `receipt-ocr-igw` |

### 4. デフォルト・セキュリティ・リスト

まず、VM設定を行っているMacの現在のグローバルIPv4アドレスを確認する。以下では例として
`203.0.113.10` を使うが、実際の値に置き換える。

デフォルト・セキュリティ・リストのIngressルールを確認し、SSHを `0.0.0.0/0` から許可するルールがあれば
削除する。その後、次を追加する。

| 項目 | 設定値 |
| --- | --- |
| ステートレス | OFF（ステートフル） |
| ソース・タイプ | CIDR |
| ソースCIDR | `203.0.113.10/32`（自分のグローバルIPv4） |
| IPプロトコル | TCP |
| ソース・ポート | すべて |
| 宛先ポート | `22` |
| 説明 | `SSH from home` |

既存のICMPルールは削除しなくてよい。Egressはデフォルトの「すべてのプロトコル、宛先 `0.0.0.0/0`」を
残す。これはVMからOS更新、GitHub、Google APIへ接続するためで、インターネットからVMへの受信を許可する
ルールではない。

自宅回線のグローバルIPが変わってSSHできなくなった場合は、SSHを全世界公開せず、この `/32` を新しいIPへ
更新する。

### 5. 公開サブネット

VCN詳細の「サブネット」→「サブネットの作成」を選択する。

| 項目 | 設定値 |
| --- | --- |
| 名前 | `receipt-ocr-public-subnet` |
| サブネット・タイプ | リージョナル |
| IPv4 CIDRブロック | `10.0.0.0/24` |
| ルート表 | VCNのデフォルト・ルート表 |
| セキュリティ・リスト | VCNのデフォルト・セキュリティ・リスト |
| サブネット・アクセス | **パブリック・サブネット** |
| DNSラベル | `worker` |
| サブネット内VNICのPublic IPv4を禁止 | OFF |
| IPv6 | 無効 |

このPoCでは、VMへPublic IPv4を割り当ててSSH接続し、Internet Gateway経由でGitHubとGoogle APIへ
接続するため、**パブリック・サブネット**を選ぶ。パブリック・サブネットでも全ポートが自動公開されるわけでは
なく、受信可否はセキュリティ・リストで制御する。SSHのTCP 22は自分のグローバルIPv4 `/32` からだけ許可する。

サブネット作成後、VM作成画面へ戻る。

### 6. VM側のネットワーク選択

VMの「プライマリVNIC」または「ネットワーキング」で次を選ぶ。

| 項目 | 設定値 |
| --- | --- |
| VCN | `receipt-ocr-vcn` |
| サブネット | `receipt-ocr-public-subnet` |
| Public IPv4アドレスの割当て | ON（エフェメラル） |
| Private IPv4 | 自動割当て |
| Network Security Group | なし |
| DNSレコード | 有効でよい |

VM作成後、インスタンス詳細にPublic IPv4が表示されることを確認する。SSHできない場合は、Public IPv4の有無、
サブネットのルート表、Internet Gateway、Ingressの接続元 `/32` を順に確認する。

参考:

- [OCI VCNの作成](https://docs.oracle.com/en-us/iaas/Content/Network/Tasks/create_vcn.htm)
- [OCI Internet Gatewayの作成](https://docs.oracle.com/en-us/iaas/Content/Network/Tasks/create-ig.htm)

## cloud-initによるVMのセットアップ

使用するスクリプト:

```text
deploy/oci/cloud-init-poc.sh
```

このスクリプトは次を自動実行する。

- OS更新とGit、Python、ビルド依存パッケージのインストール
- タイムゾーンを `Asia/Tokyo` に設定
- `receipt-ocr` と `receipt-ocr-codex` 専用ユーザー、設定・秘密情報・共有spoolの作成
- 公開GitHubリポジトリの `main` を `/opt/receipt-ocr` へclone
- Python venv作成、依存関係インストール、ユニットテスト
- Vision/I/O worker、Codex worker、週次認証health checkのsystemd service/timer配置
- SSHパスワードログインとrootログインの無効化

サービスアカウント鍵、DriveフォルダID、世帯IDはcloud-initへ入れない。OCIのuser dataはVM内のメタデータ
として取得可能なため、秘密情報の配送には使わない。

### VM作成前

現在のPoC実装と `deploy/oci/` をcommitしてGitHubの `main` へpushする。cloud-initはGitHub上のコードを取得する
ため、ローカルにしかない変更はVMへ反映されない。

```bash
git status
git push origin main
```

### OCI Console

1. この文書の手順でVCNと公開サブネットを先に作成する。
2. イメージで通常版の `Oracle Linux 9` を選ぶ。
3. シェイプで `VM.Standard.A1.Flex`、1 OCPU、6GBを選ぶ。
4. VCNに `receipt-ocr-vcn`、サブネットに `receipt-ocr-public-subnet` を選び、Public IPv4を割り当てる。
5. ブートボリュームを50GBにする。
6. SSH公開鍵を登録する。
7. 「拡張オプション」→「管理」→「初期化スクリプト」を開く。
8. 「cloud-initスクリプト・ファイルの選択」で `deploy/oci/cloud-init-poc.sh` をアップロードする。
9. インスタンスを作成する。

cloud-initは初回起動時だけ実行される。完了にはOS更新とPythonパッケージ取得を含めて数分かかる。

### 起動後の確認

詳細な確認項目と期待値は[OCI VM作成後の動作確認](OCI_VM_VERIFICATION.md)を参照する。

```bash
ssh opc@VM_PUBLIC_IP
sudo cloud-init status --wait
sudo tail -n 200 /var/log/receipt-ocr-cloud-init.log
sudo test -f /var/lib/receipt-ocr-poc/bootstrap-complete
sudo systemctl status receipt-ocr-poc.timer
```

timerが `disabled` / `inactive` なのは正常。秘密情報がない状態で誤ってVisionを呼ばないよう、cloud-initでは
起動しない。

cloud-initが失敗した場合は次を確認する。

```bash
sudo cloud-init status --long
sudo less /var/log/cloud-init-output.log
sudo less /var/log/receipt-ocr-cloud-init.log
```

PoC実装の必要ファイルが見つからない場合、GitHubへのcommit/push漏れである。コードをpushした後、設定途中の
VMを手修正せず、PoCではVMを作り直してcloud-initの再現性を確認する。

## 秘密情報と実設定の配置

Google Drive、Cloud Vision、Firestoreのサービスアカウント作成から、鍵の配置、dry-run、1件処理、
timer有効化までの実作業は[OCI PoCワーカーの認証設定と稼働開始](OCI_POC_WORKER_ACTIVATION.md)を参照する。

VM用設定には `deploy/oci/config.poc.example.json` を使用する。Mac用 `config/config.json` はパスと用途が異なるため
VMへ転送しない。Firestore鍵のローカル名は `secrets/firebase-service-account.json`、VM上の配置名は
`/etc/receipt-ocr-poc/secrets/firestore.json` とする。

## ワーカーの有効化

最初に手動でdry-runと1件処理を確認し、その後timerを有効にする。

手動CLIではsystemdの `EnvironmentFile` が自動適用されないため、`config.env` を明示的に読み込む必要がある。
正しいコマンドと合格条件は[OCI PoCワーカーの認証設定と稼働開始](OCI_POC_WORKER_ACTIVATION.md)の
「dry-run」以降を使用する。

## 手動セットアップ（cloud-initを使わない場合）

1. OSユーザー `receipt-ocr` を作成し、このリポジトリを `/opt/receipt-ocr` へcloneする。
2. Python仮想環境を作成し、`pip install -e /opt/receipt-ocr` でパッケージをインストールする。
3. `deploy/oci/config.example.env` を `/etc/receipt-ocr-poc/config.env` へコピーする。
4. 3つのサービスアカウントJSONファイルを `/etc/receipt-ocr-poc/secrets/` に配置する。所有者を
   `receipt-ocr` にし、ディレクトリの権限を `0700`、各ファイルの権限を `0600` に設定する。
5. 本番環境とは独立した設定JSONを `/etc/receipt-ocr-poc/config.json` に配置する。このファイルには通常の
   `paths`、`parser`、`categories` セクションを含める。
6. serviceファイルとtimerファイルを `/etc/systemd/system/` へコピーし、
   `systemctl enable --now receipt-ocr-poc.timer` でtimerを有効化する。

Drive用認証情報に必要なのは、明示的に共有されたPoCフォルダへの `drive.readonly` アクセスだけである。
Vision用認証情報には、OCR専用Google Cloudプロジェクトのサービスアカウントを使用する。Firestore用認証情報には、
PoCコレクションを格納するプロジェクトのAdmin SDKサービスアカウントを使用する。

## ワーカーの手動確認

実行コマンドは[OCI PoCワーカーの認証設定と稼働開始](OCI_POC_WORKER_ACTIVATION.md)を参照する。
すべて `receipt-ocr` ユーザーで実行し、先に `/etc/receipt-ocr-poc/config.env` を読み込む。

`unknown_after_request` は自動再試行しない。Vision呼び出しによって、すでに1ユニット消費されている可能性が
あるためである。明示的な `retry` コマンドはジョブを再予約可能な状態へ戻すだけで、次回実行時には追加で
1ユニットを消費する。同じコマンドで `vision_reserved` ジョブを復旧できるのは、保存された状態からVisionへの
リクエストが開始されていないと確認できる場合だけである。

PoC開始前に `firestore.rules` をデプロイする。ログイン済みのWebユーザーは3つのPoCコレクションを読み取れるが、
ジョブ、結果、利用数カウンタには書き込めない。
