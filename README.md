# receipt-ocr

家庭用レシートOCRのMVPです。

まずは MacBook 上で、`data/inbox/` に置いた画像をOCRし、SQLite DBとCSVへ保存します。
Google Drive / Google Sheets 連携は後から同じパイプラインに接続できる構成です。
現時点では Google Drive for desktop などで同期されたローカルフォルダからの取り込みに対応しています。

OCR は `note-scraper` と同じく macOS 標準の Vision フレームワークを Swift 経由で使います。
追加のOCRサーバーや外部APIは使いません。

## 初期設定

```bash
cd receipt-ocr
python3 -m venv .venv
. .venv/bin/activate
cp config/config.example.json config/config.json
mkdir -p data/inbox data/processed data/failed data/export logs secrets
```

デフォルトでは macOS Vision OCR を使います。
別コマンドを使いたい場合だけ、`config/config.json` の `ocr.backend` を `command` に変更してください。

## ローカル処理

```bash
. .venv/bin/activate
python -m receipt_ocr run --payer wife
```

処理後:

- DB: `data/receipts.sqlite3`
- CSV: `data/export/receipts.csv`, `data/export/items.csv`
- 処理済み画像: `data/processed/`
- 失敗画像: `data/failed/`

## Google Drive同期フォルダから取り込み

Google Drive for desktop でMacに同期されたフォルダを使う場合は、`config/config.json` の `drive` を設定します。
詳しい運用方針は `docs/GOOGLE_DRIVE_DESKTOP.md` にまとめています。

```json
"drive": {
  "enabled": true,
  "source_dir": "~/Google Drive/receipt-inbox",
  "after_import": "archive",
  "archive_dir": "~/Google Drive/receipt-processed"
}
```

取り込みだけ:

```bash
python -m receipt_ocr sync-drive
```

取り込み後にOCRまで実行:

```bash
python -m receipt_ocr run --sync-drive
```

`after_import` は `archive`, `keep`, `delete` を指定できます。

## 未分類レビュー画面

OCR後に `未分類` になった商品は、ローカルWeb画面で確認できます。

```bash
python -m receipt_ocr review
```

Mac上で開く:

```text
http://127.0.0.1:8765
```

同じWi-Fiのスマホから開く場合は、MacのIPアドレスを使って起動します。

```bash
python -m receipt_ocr review --host 0.0.0.0 --port 8765
```

画面でカテゴリを登録すると、DBとCSVが更新され、選んだキーワードが `config/config.json` の辞書にも追加されます。

## Android専用アプリからのアップロード

Android 12以降向けの専用アプリは `android-app/` にあります。初回に支払者名と共有
`receipt-inbox` を選択すると、撮影画像をWi-Fi接続時にDriveへ直接アップロードします。
アプリが付けるファイル名には支払者名が含まれるため、通常は `--payer` が不要です。
Open Camera + FolderSyncから移行する場合など、従来名の画像には引き続き
`--payer wife` のようにフォールバックを指定できます。

無料運用を優先し、保存先を指定できるカメラアプリでレシート画像を専用フォルダへ保存し、FolderSyncでGoogle Driveの `receipt-inbox` へアップロードする方針です。

## 次に足すもの

1. Android側: 保存先指定カメラ + FolderSyncでGoogle Drive共有フォルダへ自動アップロード
2. MacBook側: 必要ならGoogle Drive APIで `inbox` を取得し、処理後に移動/削除
3. Google Sheets APIで最終家計簿へ追記
