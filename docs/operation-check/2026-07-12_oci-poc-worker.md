# OCI PoCワーカー動作確認ログ 2026-07-12

## 概要

OCI VM上の `receipt-ocr` PoCワーカーについて、Google DriveのPoCフォルダから画像を検出し、Cloud Vision APIでOCRし、FirestoreへPoCジョブ状態を書き込むところまで確認した。

この確認では、通常運用の `receipt-inbox` ではなく、PoC専用の `receipt-inbox-poc` を使用した。

## 確認対象

| 項目 | 値 |
| --- | --- |
| VM | OCI Always Free想定のAmpere VM |
| OS | Oracle Linux Server 9.8 |
| アーキテクチャ | `aarch64` |
| Python | 3.9.25 |
| 実行ユーザー | `receipt-ocr` |
| アプリ配置 | `/opt/receipt-ocr` |
| 設定ファイル | `/etc/receipt-ocr-poc/config.json` |
| 環境変数 | `/etc/receipt-ocr-poc/config.env` |
| Driveフォルダ | `receipt-inbox-poc` |
| テスト画像 | `20260712_121743.jpg` |
| DriveファイルID | `190gyywhrTZpRlC54hMu9TcOa75TuYgIJ` |

## 実行結果

### 1. dry-run

`cloud-worker --poc --dry-run` を実行し、Drive上の候補画像を検出できた。

```json
{"status": "candidate", "driveFileId": "190gyywhrTZpRlC54hMu9TcOa75TuYgIJ", "sourceName": "20260712_121743.jpg"}
```

この段階では、画像ダウンロード、Vision API呼び出し、Firestore書き込みは行わない。

### 2. 支払者未設定による入力検証エラー

手動で配置した画像ファイル名 `20260712_121743.jpg` には、Androidアプリ形式の支払者情報が含まれていなかった。

そのため、最初の `cloud-worker --poc --once` は次の結果になった。

```json
{
  "status": "invalid_source",
  "driveFileId": "190gyywhrTZpRlC54hMu9TcOa75TuYgIJ",
  "error": "Payer is missing from filename and --payer was not supplied: 20260712_121743.jpg"
}
```

対処として、`/etc/receipt-ocr-poc/config.env` に次を設定した。

```dotenv
POC_DEFAULT_PAYER=ken
```

Androidアプリ形式のファイル名を使う場合、この設定は不要にできる。

### 3. Billing未有効によるVision APIエラー

Cloud Vision APIの初回呼び出し時、Google CloudプロジェクトにBillingが有効化されていなかったため、次のエラーになった。

```json
{
  "status": "unknown_after_request",
  "driveFileId": "190gyywhrTZpRlC54hMu9TcOa75TuYgIJ",
  "error": "403 This API method requires billing to be enabled. ..."
}
```

確認できた原因:

- `reason: BILLING_DISABLED`
- `service: vision.googleapis.com`
- `consumer: projects/142442677268`

Cloud Vision APIは無料枠内で使う場合でも、Billingの有効化が必要である。

この失敗は、Vision APIへリクエストを送った後の失敗として扱われるため、ジョブ状態は `unknown_after_request` になった。この状態は重複課金防止のため自動再試行しない。

Billing有効化後、次のコマンドで対象ファイルを手動再試行可能状態へ戻した。

```bash
sudo -u receipt-ocr /bin/bash -c '
  set -a
  source /etc/receipt-ocr-poc/config.env
  set +a
  exec /opt/receipt-ocr/.venv/bin/python \
    -m receipt_ocr \
    --config /etc/receipt-ocr-poc/config.json \
    cloud-worker retry 190gyywhrTZpRlC54hMu9TcOa75TuYgIJ --poc
'
```

### 4. Vision OCRとFirestore書き込み

Billing有効化と手動retry後、`cloud-worker --poc --once` を再実行し、次の結果になった。

```json
{"status": "needs_review", "driveFileId": "190gyywhrTZpRlC54hMu9TcOa75TuYgIJ"}
```

この結果により、次を確認できた。

- Driveから画像を取得できた
- Cloud Vision APIでOCRできた
- OCR結果を既存の解析処理へ渡せた
- FirestoreへPoCジョブ状態を書き込めた
- 自動確定条件を満たさない場合に `needs_review` へできた

`needs_review` は失敗ではない。合計不一致、未分類、必須項目欠落など、確認が必要な場合の正常な状態である。

### 5. status確認

`cloud-worker status --poc` でFirestore上のジョブ状態を確認した。

```json
[
  {
    "driveFileId": "190gyywhrTZpRlC54hMu9TcOa75TuYgIJ",
    "status": "needs_review",
    "payer": "ken",
    "visionAttempted": true,
    "sourceName": "20260712_121743.jpg",
    "visionUnits": 2,
    "createdAt": "2026-07-12 03:37:39.863000+00:00",
    "error": null,
    "updatedAt": "2026-07-12 03:48:26.701000+00:00"
  }
]
```

`visionUnits` が `2` になっているのは、Billing未有効時の `unknown_after_request` でも安全側にVision試行済みとして1回予約し、その後の成功処理でもう1回予約したためである。

### 6. 重複Vision呼び出し防止

同じDriveファイルを残したまま `cloud-worker --poc --once` を再実行した。

```json
{"status": "idle"}
```

その後の `cloud-worker status --poc` でも `visionUnits` は `2` のままだった。

これにより、同じDriveファイルIDに対して、`needs_review` のジョブは再処理されず、Vision APIを重複呼び出ししないことを確認した。

## 確認済み

- VMからGoogle Drive APIへ接続できる
- PoC専用Driveフォルダを列挙できる
- PoC専用Driveフォルダ内の画像を候補として検出できる
- 支払者未設定時に `invalid_source` で止まる
- Cloud Vision APIのBilling未有効時に `unknown_after_request` で止まる
- `unknown_after_request` は自動再試行しない
- 手動retryで再試行可能状態に戻せる
- Cloud Vision APIでOCRできる
- FirestoreへPoCジョブを書き込める
- 自動確定できないレシートを `needs_review` にできる
- 同じDriveファイルIDを再実行してもVision利用数が増えない

## 未確認

- `poc_receipts/{driveFileId}` の保存内容確認
- `reviewReason` の確認
- 複数レシートでのOCR精度確認
- 自動確定 `completed` になるレシートの確認
- timerによる自動実行
- timer実行時のjournalログ確認
- Androidアプリ形式ファイル名による支払者自動判定

## 次の確認手順

### 1. FirestoreのPoCレシート内容を確認する

Firebase ConsoleのFirestore Databaseで次を確認する。

```text
households/{POC_HOUSEHOLD_ID}/poc_receipts/190gyywhrTZpRlC54hMu9TcOa75TuYgIJ
```

確認項目:

- `shopName`
- `purchasedAt`
- `totalAmount`
- `payer`
- `status`
- `reviewReason`

`reviewReason` を見て、なぜ `needs_review` になったかを確認する。

### 2. 追加で2〜3枚を手動処理する

PoC段階ではtimerをすぐ有効化せず、まず画像を1枚ずつ追加して手動実行する。

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

期待結果:

- `completed`
- `needs_review`

`failed` または `unknown_after_request` が出た場合は、timerを有効化せず原因を確認する。

### 3. 重複防止を再確認する

各画像について、同じDriveファイルIDの再実行で `idle` になり、`visionUnits` が増えないことを確認する。

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

### 4. timerを有効化する

手動確認で問題なければ、timerを有効化する。

```bash
sudo systemctl enable --now receipt-ocr-poc.timer
sudo systemctl status receipt-ocr-poc.timer --no-pager
```

timer実行ログを確認する。

```bash
sudo journalctl -u receipt-ocr-poc.service -n 100 --no-pager
```

## 注意事項

### Python 3.9警告

実行時にGoogleライブラリからPython 3.9のサポート終了警告が表示される。

PoC継続のブロッカーではないが、本番運用に寄せる場合はPython 3.11または3.12への移行を検討する。

### Vision利用数

このPoC実装では、Vision APIへリクエストを送った後に結果が不明な失敗は `unknown_after_request` とし、自動再試行しない。

これは重複課金防止のための安全側の動作である。再試行する場合は、`cloud-worker retry <driveFileId> --poc` を明示的に実行する。

### Billing

Cloud Vision APIは無料枠内で使う場合でも、Google Cloud Billingの有効化が必要である。

Billing有効化後も、次の安全策を維持する。

- Google Cloud Billingの少額予算アラート
- Vision APIの低い分単位クォータ
- `POC_MAX_VISION_UNITS=20`
- PoC専用Driveフォルダだけをサービスアカウントへ共有
