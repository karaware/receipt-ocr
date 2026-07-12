# OCI PoCワーカーの認証設定と稼働開始

VM基盤の確認が完了した後、Google Drive、Cloud Vision、Firestoreの認証情報を設定し、
PoCワーカーを安全に稼働させるための手順を示す。

この手順が完了するまで `receipt-ocr-poc.timer` は有効化しない。最初にdry-run、次にテスト画像1枚の
手動処理を行い、FirestoreとVision利用数を確認してから自動実行へ移行する。

## 全体の作業順序

0. VMのリポジトリを最新化する
1. Google DriveにPoC専用フォルダを作る
2. Drive閲覧専用サービスアカウントを作る
3. Cloud Vision APIとOCR専用サービスアカウントを準備する
4. Firestore Security Rulesをデプロイする
5. 3つのJSON鍵をVMへ配置する
6. VMのPoC設定ファイルを作る
7. dry-runでDrive接続だけを確認する
8. テスト画像1枚を手動処理する
9. 冪等性とVision利用数を確認する
10. Codex CLIをChatGPTで認証し、LLM経路を確認する
11. systemd timerを有効化する

## 事前条件

- [OCI VM作成後の動作確認](OCI_VM_VERIFICATION.md)がすべて合格している
- VMのPublic IPv4とSSH秘密鍵が分かる
- Macの `secrets/` がGit管理対象外になっている
- Firebase家計簿の世帯IDが分かる。現在の既定値は `hirata-household`
- Firebase Admin SDK鍵 `secrets/firebase-service-account.json` がある
- Google CloudとFirebaseを管理できるGoogleアカウントでログインできる

秘密鍵JSONの内容をチャット、Git、cloud-init、OCIのuser dataへ貼り付けない。

## 0. VMのリポジトリを最新化する

この手順書とVM用設定テンプレートを含む変更がGitHubの `main` へpushされた後、VMへSSH接続して実行する。

```bash
sudo -u receipt-ocr git -C /opt/receipt-ocr pull --ff-only
sudo -u receipt-ocr git -C /opt/receipt-ocr status --short --branch
test -f /opt/receipt-ocr/deploy/oci/config.poc.example.json \
  && echo "PoC config template OK"
```

ブランチが `main`、作業ツリーがcleanで、`PoC config template OK` と表示されることを確認する。
`pull` が失敗した場合は先へ進まず、VM上の変更やGitHubへのpush漏れを確認する。

## 1. Google DriveのPoCフォルダ

通常運用の `receipt-inbox` とは分離し、PoC専用フォルダだけをサービスアカウントへ公開する。

1. ブラウザでGoogle Driveを開く。
2. マイドライブに `receipt-inbox-poc` フォルダを作る。
3. フォルダを開き、ブラウザのURLを確認する。
4. URLの `/folders/` より後ろにある文字列をDriveフォルダIDとして控える。

```text
https://drive.google.com/drive/folders/DRIVE_FOLDER_ID
                                       ^^^^^^^^^^^^^^^
```

この段階ではテスト画像を入れない。

## 2. Drive閲覧用サービスアカウント

### 2.1 Drive APIを有効化する

1. [Google Cloud Console](https://console.cloud.google.com/)を開く。
2. receipt-ocr用Google Cloudプロジェクトを選ぶ。
3. 「APIとサービス」→「ライブラリ」を開く。
4. `Google Drive API` を検索して「有効にする」を押す。

### 2.2 サービスアカウントとJSON鍵を作る

1. 「IAMと管理」→「サービス アカウント」を開く。
2. 「サービス アカウントを作成」を押す。
3. 名前を `receipt-drive-reader` にする。
4. 「このサービス アカウントにプロジェクトへのアクセスを許可」は空欄のまま完了する。
5. 作成したサービスアカウントを開き、「キー」→「鍵を追加」→「新しい鍵を作成」を選ぶ。
6. キーのタイプにJSONを選び、ダウンロードする。
7. Macのリポジトリ内へ次の名前で移動する。

```text
/Users/k-hirata/Documents/receipt-ocr/secrets/drive.json
```

プロジェクトIAMロールは付けない。Driveへのアクセス権は次のフォルダ共有で付与する。

### 2.3 PoCフォルダだけを共有する

1. サービスアカウント詳細に表示されるメールアドレスをコピーする。
2. Google Driveで `receipt-inbox-poc` の共有画面を開く。
3. サービスアカウントのメールアドレスを追加する。
4. 権限を「閲覧者」にする。
5. 通知は送信しなくてよい。

ワーカーは `drive.readonly` スコープを使用し、共有されたフォルダ直下の画像を列挙・ダウンロードする。
通常の `receipt-inbox` やマイドライブ全体は共有しない。

参考: [Google Drive APIでの共有と権限](https://developers.google.com/workspace/drive/api/guides/manage-sharing)

## 3. Cloud Vision用サービスアカウント

### 3.1 課金条件を確認する

Cloud Vision APIはOCI Always FreeやFirebase Sparkとは別のGoogle Cloudサービスである。APIを利用する
Google Cloudプロジェクトには請求先アカウントの関連付けが必要になる。

この実装はFirestoreの通算カウンタにより、PoC全体のVision予約数を最大20回に制限する。ただし、次も行う。

- Google Cloud Billingで少額の予算アラートを作る
- Vision APIのリクエストクォータをPoCに必要な低い値へ下げる
- `POC_MAX_VISION_UNITS=20` を増やさない

予算アラートは通知機能であり、APIを自動停止する上限ではない。20回のアプリ側上限を主制御として扱う。

2026年6月時点では、Document Text Detectionは月初の1,000ユニットまで無料である。PoCの20回は通常この
無料利用分に収まるが、同じプロジェクトのほかの利用も合算されるため、以下の防御をすべて設定する。

参考: [Cloud Vision APIの料金](https://cloud.google.com/vision/pricing)

#### 3.1.1 予算アラートを作る

1. Google Cloud Console上部で、Vision APIを使用するプロジェクトを選ぶ。
2. ナビゲーションメニューから「お支払い」→「予算とアラート」を開く。
3. 意図した請求先アカウントが表示されていることを確認する。
4. 「予算を作成」を押す。
5. 次の値を設定する。

| 項目 | 設定値 |
| --- | --- |
| 名前 | `receipt-ocr-vision-poc` |
| 期間 | 毎月 |
| プロジェクト | Vision APIを使用するプロジェクトだけ |
| サービス | すべてのサービス |
| 予算タイプ | 指定額 |
| 予算額 | `100円`、または画面で入力可能な最低額 |

サービスをVisionだけに絞らず、対象プロジェクト全体を監視する。これにより、誤って別の有料サービスを
有効化した場合も検知できる。

6. アラートしきい値を次のように設定する。

| しきい値 | トリガー |
| ---: | --- |
| 1% | 実際の費用 |
| 50% | 実際の費用 |
| 100% | 実際の費用 |

1%を入力できない場合は、画面で許可される最小値を設定する。「予測費用」ではなく「実際の費用」を使う。

7. 「請求先アカウントの管理者とユーザーにメール通知」を有効にする。
8. 予算を作成する。
9. 一覧に `receipt-ocr-vision-poc` と指定した予算額が表示されることを確認する。

予算を超えてもAPIは停止しない。また、費用集計とメールには遅延があるため、予算アラートだけを上限管理として
使用しない。

参考: [Google Cloudの予算と予算アラート](https://cloud.google.com/billing/docs/how-to/budgets)

#### 3.1.2 Vision APIのクォータを下げる

このワーカーは5分ごとに最大1画像を処理するため、1分あたり2リクエストで十分である。

1. Google Cloud Console上部で、Vision APIを使用するプロジェクトを選ぶ。
2. 「APIとサービス」→「有効なAPIとサービス」を開く。
3. `Cloud Vision API` を選ぶ。
4. 「割り当てとシステム上限」または「Quotas & System Limits」タブを開く。
5. フィルタで次の割り当てを検索する。

```text
Requests per minute
Text detection requests per minute
```

6. 対象行を選び、「割り当てを編集」または「Edit quotas」を押す。
7. 設定可能な項目を次の値へ変更する。

| 割り当て | 設定値 |
| --- | ---: |
| Requests per minute | `2` |
| Text detection requests per minute | `2` |

「プロジェクト単位」と「プロジェクト・ユーザー単位」の両方が表示される場合は、両方を `2` にする。
変更を送信後、割り当て一覧の値が反映されたことを確認する。反映には時間がかかる場合がある。

編集ボタンが表示されない場合は、操作中のアカウントにQuota Administrator
（`roles/servicemanagement.quotaAdmin`）相当の権限があるか確認する。項目自体が変更不可の場合は無理に別の
割り当てを変更せず、Firestoreの20回制限を維持する。

このクォータは短時間の大量呼び出しを抑制するが、月間または通算の費用上限ではない。1分ごとに回復するため、
PoC全体の20回制限はFirestoreカウンタで行う。

参考:

- [Cloud Vision APIの割り当てと上限](https://cloud.google.com/vision/quotas)
- [Google Cloudの割り当て表示・変更](https://cloud.google.com/docs/quotas/view-manage)

#### 3.1.3 VM側の20回制限を確認する

「6. VM用設定ファイル」で `/etc/receipt-ocr-poc/config.env` を作成した後、次の値を維持する。

```dotenv
POC_MAX_VISION_UNITS=20
```

VMで設定値を確認する。

```bash
sudo grep '^POC_MAX_VISION_UNITS=' \
  /etc/receipt-ocr-poc/config.env
```

期待値:

```text
POC_MAX_VISION_UNITS=20
```

このカウンタはFirestoreプロジェクトと世帯IDの組合せに保存される。PoC途中で
`POC_FIRESTORE_SERVICE_ACCOUNT_PATH` が指すプロジェクトや `POC_HOUSEHOLD_ID` を変更すると別カウンタに
なるため、20回の検証が完了するまで変更しない。

### 3.2 Vision APIを有効化する

1. Google Cloud ConsoleでOCRに使用するプロジェクトを選ぶ。
2. 「お支払い」で意図した請求先アカウントが関連付いていることを確認する。
3. 「APIとサービス」→「ライブラリ」を開く。
4. `Cloud Vision API` を検索して「有効にする」を押す。

参考: [Cloud Vision APIのセットアップ](https://cloud.google.com/vision/docs/setup)

### 3.3 サービスアカウントとJSON鍵を作る

1. 「IAMと管理」→「サービス アカウント」を開く。
2. 名前 `receipt-vision-worker` でサービスアカウントを作る。
3. ロールに「Service Usage Consumer」を付ける。
4. 作成したサービスアカウントの「キー」からJSON鍵を作る。
5. Macのリポジトリ内へ次の名前で移動する。

```text
/Users/k-hirata/Documents/receipt-ocr/secrets/vision.json
```

画像はVMからVision APIへ直接送信するため、Cloud Storageのロールは付けない。

参考:

- [Cloud Vision APIの認証](https://cloud.google.com/vision/docs/authentication)
- [Service UsageのIAMロール](https://cloud.google.com/iam/docs/roles-permissions/serviceusage)

## 4. Firestoreの準備

Firestoreには既存のFirebase Admin SDK鍵を使用する。新しい鍵は作らない。

```text
/Users/k-hirata/Documents/receipt-ocr/secrets/firebase-service-account.json
```

Admin SDKはFirestore Security Rulesを迂回できるため、この鍵はVM上でも `0600` で保存する。

PoCを開始する前にMacでSecurity Rulesとインデックスをデプロイする。

```bash
cd /Users/k-hirata/Documents/receipt-ocr
firebase deploy --only firestore
```

最後に `Deploy complete!` と表示されることを確認する。Webログイン利用者はPoCコレクションを読み取れるが、
`poc_ocr_jobs`、`poc_ocr_usage`、`poc_receipts` へ直接書き込めない設定になる。

## 5. JSON鍵をVMへ転送する

Macのターミナルで実行する。値は実際のものへ置き換える。

```bash
cd /Users/k-hirata/Documents/receipt-ocr

VM_PUBLIC_IP="VMのPublic IPv4"
SSH_KEY="secrets/OCIのSSH秘密鍵ファイル名"

chmod 600 "$SSH_KEY"

scp -i "$SSH_KEY" -o IdentitiesOnly=yes \
  secrets/drive.json \
  secrets/vision.json \
  opc@"$VM_PUBLIC_IP":/home/opc/

scp -i "$SSH_KEY" -o IdentitiesOnly=yes \
  secrets/firebase-service-account.json \
  opc@"$VM_PUBLIC_IP":/home/opc/firestore.json

ssh -i "$SSH_KEY" -o IdentitiesOnly=yes opc@"$VM_PUBLIC_IP"
```

以降はSSH接続したVM内で実行する。

```bash
sudo install -o receipt-ocr -g receipt-ocr -m 0600 \
  /home/opc/drive.json /etc/receipt-ocr-poc/secrets/drive.json

sudo install -o receipt-ocr -g receipt-ocr -m 0600 \
  /home/opc/vision.json /etc/receipt-ocr-poc/secrets/vision.json

sudo install -o receipt-ocr -g receipt-ocr -m 0600 \
  /home/opc/firestore.json /etc/receipt-ocr-poc/secrets/firestore.json

rm /home/opc/drive.json /home/opc/vision.json /home/opc/firestore.json
```

一時転送先から削除した後、配置結果を確認する。JSON本文は表示しない。

```bash
sudo find /etc/receipt-ocr-poc/secrets \
  -maxdepth 1 -type f -printf '%f %u:%g %m\n'
```

期待値:

```text
drive.json receipt-ocr:receipt-ocr 600
vision.json receipt-ocr:receipt-ocr 600
firestore.json receipt-ocr:receipt-ocr 600
```

## 6. VM用設定ファイル

VMにはMac用 `config/config.json` を流用せず、VM専用テンプレートを使う。テンプレートのデータパスは
systemdサービスが書き込める `/var/lib/receipt-ocr-poc/` 配下に設定済みである。

```bash
sudo install -o root -g receipt-ocr -m 0640 \
  /opt/receipt-ocr/deploy/oci/config.poc.example.json \
  /etc/receipt-ocr-poc/config.json

sudo install -o root -g receipt-ocr -m 0640 \
  /opt/receipt-ocr/deploy/oci/config.example.env \
  /etc/receipt-ocr-poc/config.env

sudo vi /etc/receipt-ocr-poc/config.env
```

最低限、次の2項目を実値へ変更する。

```dotenv
POC_DRIVE_FOLDER_ID=手順1で控えたDriveフォルダID
POC_HOUSEHOLD_ID=hirata-household
```

残りは次の値を維持する。

```dotenv
POC_DRIVE_SERVICE_ACCOUNT_PATH=/etc/receipt-ocr-poc/secrets/drive.json
POC_VISION_SERVICE_ACCOUNT_PATH=/etc/receipt-ocr-poc/secrets/vision.json
POC_FIRESTORE_SERVICE_ACCOUNT_PATH=/etc/receipt-ocr-poc/secrets/firestore.json
POC_WORK_DIR=/var/lib/receipt-ocr-poc/work
POC_MAX_VISION_UNITS=20
```

Androidアプリが作成した画像はファイル名に支払者を含む。手作業で名前を付けたJPEGを試す場合だけ、
`config.env` の末尾へ一時的に次を追加する。

```dotenv
POC_DEFAULT_PAYER=me
```

`me` は実際に使用する支払者名へ置き換える。Androidアプリ形式の画像だけを使う運用へ移行したら、この行は
削除できる。

設定値とファイルの読取り可否を検査する。秘密情報の本文は出力しない。

```bash
sudo -u receipt-ocr /bin/bash -c '
  set -e
  test -r /etc/receipt-ocr-poc/config.json
  test -r /etc/receipt-ocr-poc/config.env
  test -r /etc/receipt-ocr-poc/secrets/drive.json
  test -r /etc/receipt-ocr-poc/secrets/vision.json
  test -r /etc/receipt-ocr-poc/secrets/firestore.json
  echo "configuration files readable"
'
```

## 7. dry-run

最初は `receipt-inbox-poc` を空にしたまま実行する。`config.env` はsystemd専用形式なので、手動実行時は
明示的に読み込む。

```bash
sudo -u receipt-ocr /bin/bash -c '
  set -a
  source /etc/receipt-ocr-poc/config.env
  set +a
  exec /opt/receipt-ocr/.venv/bin/python \
    -m receipt_ocr \
    --config /etc/receipt-ocr-poc/config.json \
    cloud-worker --poc --dry-run
'
```

空のフォルダへ正常に接続できた場合の期待値:

```json
{"status": "idle"}
```

dry-runはDriveを列挙するが、画像のダウンロード、Vision呼び出し、Firestore書込みを行わない。

代表的なエラー:

| エラー | 確認箇所 |
| --- | --- |
| `File not found` / `404` | DriveフォルダID、サービスアカウントへのフォルダ共有 |
| `403` / `insufficientPermissions` | Drive APIの有効化、共有権限が「閲覧者」以上か |
| JSON鍵を読めない | ファイル名、所有者、権限が`0600`か |

## 8. テスト画像1枚の手動処理

1. `receipt-inbox-poc` にレシート画像を1枚だけ置く。
2. Androidアプリで撮影したファイル名を使うか、`POC_DEFAULT_PAYER` を設定する。
3. もう一度dry-runを実行する。

候補を認識した場合の例:

```json
{"status": "candidate", "driveFileId": "...", "sourceName": "...jpg"}
```

この時点でもVisionは呼ばれない。候補が正しいことを確認してから1回だけ処理する。

```bash
sudo -u receipt-ocr /bin/bash -c '
  set -a
  source /etc/receipt-ocr-poc/config.env
  set +a
  exec /opt/receipt-ocr/.venv/bin/python \
    -m receipt_ocr \
    --config /etc/receipt-ocr-poc/config.json \
    cloud-worker --poc --once
'
```

正常な終了状態は次のどちらかである。

| 状態 | 意味 |
| --- | --- |
| `completed` | 必須項目、カテゴリ、合計が揃い自動確定できた |
| `needs_review` | OCRは完了したが確認が必要 |

`invalid_source` は支払者をファイル名から取得できず、`POC_DEFAULT_PAYER` もない状態である。
`failed` または `unknown_after_request` の場合はtimerを有効化せず、「12. 障害時の扱い」を確認する。

## 9. Firestoreと重複防止の確認

Firebase Consoleの「Firestore Database」→「データ」で次を確認する。

```text
households
  hirata-household
    poc_ocr_jobs
      DRIVE_FILE_ID
    poc_receipts
      DRIVE_FILE_ID
    poc_ocr_usage
      _total
      YYYY-MM
```

期待値:

- `poc_ocr_jobs/DRIVE_FILE_ID.status` が `completed` または `needs_review`
- `poc_receipts/DRIVE_FILE_ID` に店名、購入日、合計、支払者、確認状態がある
- `poc_ocr_usage/_total.units` が `1`
- OCR全文とレシート画像がFirestoreに保存されていない

VMでジョブ一覧を確認する場合は次を実行する。

```bash
sudo -u receipt-ocr /bin/bash -c '
  set -a
  source /etc/receipt-ocr-poc/config.env
  set +a
  exec /opt/receipt-ocr/.venv/bin/python \
    -m receipt_ocr \
    --config /etc/receipt-ocr-poc/config.json \
    cloud-worker status --poc
'
```

同じ画像をDriveへ残したまま `--once` をもう一度実行する。ほかに未処理画像がなければ次になり、
`poc_ocr_usage/_total.units` が `1` のままであることを確認する。

```json
{"status": "idle"}
```

これで同一DriveファイルIDの重複処理が防止されていることを確認できる。

## 10. Codex CLIをChatGPTで認証し、LLM経路を確認する

この経路はOpenAI APIキーを使用しない。初回だけChatGPT Plusアカウントでdevice loginを行い、以後は
永続化した `auth.json` をCodex自身が更新する。通常のレシート処理に人の操作は不要である。

まず `/etc/receipt-ocr-poc/config.json` の `poc.llm.enabled` を `true` に変更する。APIキーを
`config.env`、systemd unit、ユーザー環境へ設定しない。

専用ユーザーでdevice loginを開始する。

```bash
sudo -u receipt-ocr-codex env \
  HOME=/var/lib/receipt-ocr-codex \
  CODEX_HOME=/var/lib/receipt-ocr-codex/.codex \
  /var/lib/receipt-ocr-codex/.local/bin/codex login --device-auth
```

表示されたURLとワンタイムコードを使って、ブラウザでChatGPT Plusアカウントへログインする。完了後、
本文やtokenを表示せず認証方式と権限だけを確認する。

```bash
sudo chown receipt-ocr-codex:receipt-ocr-codex \
  /var/lib/receipt-ocr-codex/.codex/auth.json
sudo chmod 0600 /var/lib/receipt-ocr-codex/.codex/auth.json

sudo -u receipt-ocr-codex jq '{
  auth_mode,
  has_refresh_token: ((.tokens.refresh_token // "") != ""),
  last_refresh
}' /var/lib/receipt-ocr-codex/.codex/auth.json
```

`auth_mode` が `chatgpt`、`has_refresh_token` が `true` であることを確認する。Google/Firebase鍵を
Codexユーザーが読めないことも確認する。

```bash
sudo -u receipt-ocr-codex test \
  ! -r /etc/receipt-ocr-poc/secrets/firestore.json
sudo -u receipt-ocr-codex test \
  ! -r /etc/receipt-ocr-poc/secrets/vision.json
sudo -u receipt-ocr-codex test \
  ! -r /etc/receipt-ocr-poc/secrets/drive.json
```

health checkを1回実行する。

```bash
sudo systemctl start receipt-ocr-llm-health.service
sudo systemctl show receipt-ocr-llm-health.service \
  --property=Result --property=ExecMainStatus
```

`Result=success`、`ExecMainStatus=0` が合格条件である。次にDriveへ新しいテスト画像を1枚置き、I/O worker、
LLM worker、I/O workerの順で1回ずつ起動する。

```bash
sudo systemctl start receipt-ocr-poc.service
sudo systemctl start receipt-ocr-llm.service
sudo systemctl start receipt-ocr-poc.service
```

1回目のI/O workerはVision OCR後に `llm_pending` を作り、LLM workerが画像とOCRをCodexへ渡す。
2回目のI/O workerが検算済み結果を正式な `receipts / transactions` へ登録する。Firestoreで次を確認する。

- `poc_ocr_jobs/DRIVE_FILE_ID.status` が `confirmed` または `needs_review`
- `receipts/DRIVE_FILE_ID.parseSource` が `codex` または `rule_fallback`
- `transactions` に同じ `receiptId` の明細がある
- `poc_receipts` にモデル、prompt/schema version、検証結果だけがあり、OCR全文と画像がない
- `system_alerts` に認証・worker停止・最終保留の未解決原因が表示される

Codexの認証が失効した場合は `codex_auth_blocked` がWeb家計簿へ表示される。通常処理は停止したままにし、
この節のdevice loginを再実行する。APIキーへ切り替えない。

参考:

- [Codex非対話モード](https://learn.chatgpt.com/docs/non-interactive-mode)
- [ヘッドレス認証](https://learn.chatgpt.com/docs/auth)
- [ChatGPT管理認証の維持](https://learn.chatgpt.com/docs/auth/ci-cd-auth)

## 11. timerを有効化する

手順10まで合格した場合だけ実行する。

```bash
sudo systemctl enable --now \
  receipt-ocr-poc.timer \
  receipt-ocr-llm.timer \
  receipt-ocr-llm-health.timer

sudo systemctl is-enabled receipt-ocr-poc.timer
sudo systemctl is-active receipt-ocr-poc.timer
sudo systemctl list-timers --all receipt-ocr-poc.timer
sudo systemctl list-timers --all \
  receipt-ocr-llm.timer receipt-ocr-llm-health.timer
```

期待値は `enabled`、`active` と、次回実行時刻の表示である。I/O workerは約5分間隔、LLM workerは
約1分間隔、認証health checkは週1回起動する。

実行結果は次で確認する。

```bash
sudo journalctl -u receipt-ocr-poc.service -n 100 --no-pager
sudo systemctl show receipt-ocr-poc.service \
  --property=Result --property=ExecMainStatus
```

24時間は定期的にログ、Firestoreの利用数、Google Cloud Billingを確認する。

timerを止める場合:

```bash
sudo systemctl disable --now \
  receipt-ocr-poc.timer \
  receipt-ocr-llm.timer \
  receipt-ocr-llm-health.timer
```

## 12. 障害時の扱い

### `failed`

Driveダウンロード前など、Visionが開始されていない失敗は次回実行で再試行される。ログとFirestoreの
`visionAttempted` を確認し、原因を直すまでtimerは停止したままにする。

### `unknown_after_request`

Visionへ要求が届いたか判断できない状態であり、自動再試行しない。再試行すると追加で1ユニット消費する
可能性がある。ログとGoogle Cloudのメトリクスを確認した上で、明示的に再試行する場合だけ次を実行する。

```bash
DRIVE_FILE_ID="対象のDriveファイルID"

sudo -u receipt-ocr /bin/bash -c '
  set -a
  source /etc/receipt-ocr-poc/config.env
  set +a
  exec /opt/receipt-ocr/.venv/bin/python \
    -m receipt_ocr \
    --config /etc/receipt-ocr-poc/config.json \
    cloud-worker retry "'"$DRIVE_FILE_ID"'" --poc
'
```

`retry_ready=true` の後、次回の `--once` またはtimer実行で再処理される。

## 完了条件

- Driveサービスアカウントが `receipt-inbox-poc` だけを閲覧できる
- Visionサービスアカウントに不要なStorage権限がない
- 3つのJSON鍵がVM上で `receipt-ocr:receipt-ocr`、`0600` になっている
- 空フォルダのdry-runが `idle` になる
- テスト画像1枚が `completed` または `needs_review` になる
- FirestoreにOCR全文と画像が保存されていない
- 同じDriveファイルを再実行してもVision利用数が増えない
- `poc_ocr_usage/_total.units` が20を超えない
- timerが `enabled`、`active` である
- Codex認証が `auth_mode: chatgpt` で、APIキーが配置されていない
- `receipt-ocr-codex` ユーザーがGoogle/Firebase鍵を読めない
- LLM timerと週次health timerが `enabled`、`active` である
