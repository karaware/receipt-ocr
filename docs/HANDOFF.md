# receipt-ocr Handoff

## 目的

家庭の家計簿入力を効率化するため、レシート画像をOCRし、最終的にGoogleスプレッドシートの家計簿へ反映する。

現状は、食費・日用品・消耗品などを人力入力している。妻と本人のAndroidスマホでレシートを撮影し、MacBook側でOCR・解析・保存する構成を目指す。

## 方針

MVPでは専用Androidアプリは作らない。

想定フロー:

```text
妻/本人のAndroid
  レシート撮影
  保存先指定カメラ + FolderSync でGoogle Drive共有フォルダへ自動アップロード

MacBook
  Google Driveからレシート画像を定期取得
  macOS Vision OCRでテキスト化
  レシート解析
  SQLiteへ保存
  CSVまたはGoogle Sheetsへ反映
  処理済み画像を移動または削除
```

無料運用を優先する。Zaimなどの有料OCR機能は使わない。

## 現在の実装

プロジェクト場所:

```text
/Users/k-hirata/Documents/receipt-ocr
```

実装済み:

- ローカル `data/inbox/` の画像を処理するCLI
- macOS Vision OCR
- OCRテキストから店名・日付・合計・明細候補を抽出
- キーワードベースのカテゴリ分類
- SQLite保存
- CSV出力
- Google Drive同期フォルダなどのローカルフォルダから `data/inbox/` へ画像を取り込むCLI

主なファイル:

- `src/receipt_ocr/ocr.py`
- `scripts/ocr_macos.swift`
- `src/receipt_ocr/parser.py`
- `src/receipt_ocr/categorizer.py`
- `src/receipt_ocr/db.py`
- `src/receipt_ocr/exporter.py`
- `src/receipt_ocr/pipeline.py`
- `src/receipt_ocr/drive_client.py`
- `docs/GOOGLE_DRIVE_DESKTOP.md`
- `docs/ANDROID_UPLOAD.md`

## OCR方式

`note-scraper` で実績のあった方式を参考にした。

参照元:

```text
/Users/k-hirata/Documents/note-scraper
```

`note-scraper` は macOS標準の Vision フレームワークをSwift経由で呼び出してOCRしていたため、同じ方式を `receipt-ocr` に組み込んだ。

現在の設定:

```json
"ocr": {
  "backend": "macos_vision",
  "timeout_seconds": 60
}
```

## ローカルOCRの試し方

レシート画像を置く:

```text
receipt-ocr/data/inbox/
```

実行:

```bash
cd /Users/k-hirata/Documents/receipt-ocr
PYTHONPATH=src python3 -m receipt_ocr run --payer me
```

妻分として登録する場合:

```bash
PYTHONPATH=src python3 -m receipt_ocr run --payer wife
```

Google Drive for desktop などの同期済みローカルフォルダから取り込む場合:

```bash
PYTHONPATH=src python3 -m receipt_ocr sync-drive
PYTHONPATH=src python3 -m receipt_ocr run --payer wife --sync-drive
```

出力:

```text
data/export/receipts.csv
data/export/items.csv
data/receipts.sqlite3
data/processed/
data/failed/
```

## 確認済み

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
PYTHONPATH=src python3 -m receipt_ocr run --payer me
CLANG_MODULE_CACHE_PATH=.swift-module-cache swift scripts/ocr_macos.swift
```

Swift単体確認は画像引数なしで `Usage: swift scripts/ocr_macos.swift <image-path>` が出るところまで確認済み。

## 未実装

- Google Drive APIから画像を取得する処理
- Google Drive API上で処理済み画像を移動または削除する処理
- Google Sheets APIへの直接追記
- Android側の実機設定確認
- `data/processed/` の古い画像を自動削除する処理

## 次にやること

1. Google Drive for desktopをストリーミングで設定する。
2. Androidに保存先を指定できるカメラアプリとFolderSyncを入れ、`receipt-inbox` への自動アップロードを試す。
3. `PYTHONPATH=src python3 -m receipt_ocr run --payer me --sync-drive` で取り込みからOCRまで確認する。
4. Web画面で `receipts` / `items` / 未分類レビューを確認する。
5. FolderSyncの無料枠で運用に足りるか確認する。
6. 最後にGoogle Sheets追記を `sheets_client.py` に実装する。

## 直近の引き継ぎ

2026-06-15時点のスマホ側設定と、次にMac側で確認する内容は以下にまとめた。

```text
docs/2026-06-15_HANDOFF.md
```
