# Google Drive for desktop 運用メモ

## 結論

`receipt-ocr` では、Google Drive for desktop を **ストリーミング** で使う前提にする。

理由:

- Macのローカルストレージ使用量を抑えられる
- Google Drive API認証を作らずに運用できる
- Finder上のフォルダを通常のローカルフォルダのように読める
- `receipt-ocr` はレシート用フォルダだけを処理対象にできる

Google公式ヘルプ:

- https://support.google.com/drive/answer/13401938
- https://support.google.com/drive/answer/10838124

## ストリーミングとミラーリングの違い

### ストリーミング

Google Drive上のファイルは主にクラウドに置かれる。Finder上には通常のファイルのように見えるが、ファイル本体は必要になったときにローカルへ取得される。

ローカルストレージはゼロではない。以下のような場合に使われる。

- ファイルを開いたとき
- アプリがファイル内容を読んだとき
- オフライン利用可能にしたとき
- 最近使ったファイルや頻繁に使うファイルがキャッシュされたとき

`receipt-ocr` は画像をOCRするためにファイル内容を読むので、その瞬間は画像がローカルにダウンロードまたはキャッシュされる。

ただし、Drive全体を常時ローカル保存するわけではない。

### ミラーリング

Google Drive上のファイルをMacのローカルディスクにも常時保存する。常にオフラインで使えるが、Drive内のファイル量に応じてMacのストレージを使う。

今回の用途では基本的に不要。

## 推奨構成

Google Drive for desktop:

```text
My Drive syncing options: Stream files
```

Google Drive上のフォルダ:

```text
receipt-inbox
receipt-processed
```

Mac上でFinderから見えるフォルダ例:

```text
~/Google Drive/receipt-inbox
~/Google Drive/receipt-processed
```

`receipt-ocr/config/config.json`:

```json
"drive": {
  "enabled": true,
  "source_dir": "~/Google Drive/receipt-inbox",
  "after_import": "archive",
  "archive_dir": "~/Google Drive/receipt-processed"
}
```

## `receipt-ocr` 側の動き

取り込みだけ:

```bash
PYTHONPATH=src python3 -m receipt_ocr sync-drive
```

取り込み後にOCRまで実行:

```bash
PYTHONPATH=src python3 -m receipt_ocr run --payer me --sync-drive
```

処理の流れ:

```text
Google Drive for desktop の receipt-inbox
  -> data/inbox にコピー
  -> source_dir 側の元画像を archive/delete/keep
  -> OCR
  -> data/processed に移動
  -> SQLite/CSV/Web画面に反映
```

## `after_import` の選び方

### `archive`

```json
"after_import": "archive"
```

取り込み後、Drive側の元画像を `archive_dir` に移動する。

最初の運用ではこれを推奨する。処理済み画像をGoogle Drive側にも残せるので、あとから確認しやすい。

### `delete`

```json
"after_import": "delete"
```

取り込み後、Drive側の元画像を削除する。

Google Drive for desktop経由の削除なので、通常はクラウド側にも削除が同期される。運用に慣れて、処理済み画像を残さなくてよいと判断してから使う。

### `keep`

```json
"after_import": "keep"
```

Drive側の元画像を残す。手動確認には向くが、同じ画像が残り続けるため運用上は非推奨。

## ローカルに残る画像

Drive側とは別に、`receipt-ocr` は処理後の画像を以下へ移動する。

```text
data/processed/
```

これはMacのローカルストレージを使う。今は自動削除機能は未実装。

将来的に足すなら、以下のどちらかがよい。

- `data/processed` の保存日数を決めて古い画像を削除する
- OCRとCSV出力が成功したら `data/processed` に残さず削除する設定を追加する

## 注意点

- `source_dir` はGoogle Drive for desktopの同期設定ではない。`receipt-ocr` が見るローカルパスを指定しているだけ。
- Drive全体を同期するか、ストリーミングにするかはGoogle Drive for desktop側で設定する。
- OCR時には画像ファイルの中身を読むため、ストリーミングでも一時的なローカル使用は発生する。
- 長期運用では `receipt-inbox` に画像を溜めない。`archive` または `delete` を使う。
