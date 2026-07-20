# Web実運用・エンドツーエンド受け入れ確認 2026-07-20

## 目的

OCI PoC VMが監視するGoogle Driveフォルダから、Cloud Vision OCR、Codex解析、Firebase Hostingの確認・確定、月次集計反映までを実運用構成で確認する。

この記録は設計・改善案の引き継ぎ書とは分離した、実施結果の記録である。

## 対象環境

| 項目 | 値 |
| --- | --- |
| 入力フォルダ | Google Drive `receipt-inbox-poc` |
| VM | `receipt-ocr-vcn` |
| Web | `https://diesel-ellipse-500009-u3.web.app` |
| 対象月 | 2026-07 |
| 支払者 | `ken` |

## 事前確認・データ整理

1. 過去の丸亀製麺レシートが同一画像の二重取り込みだったため、重複分をFirestoreから整理した。
2. `receipts` を削除しただけでは `transactions` の明細が残ることを確認した。残った孤立明細も、同じ `receiptId` を確認したうえでFirestoreから削除した。
3. 丸亀製麺の「5枚天ぷら100円引」は、`調整` ではなく `食費 / 外食`、`-100円` として確定した。
4. 2026-05のホームで支出・食費が920円、確認待ちが0件であることを確認した。

## 新規レシートの実運用確認

### 入力

通常のスマートフォンカメラで撮影したレシート画像を、手動で `receipt-inbox-poc` に1枚だけ配置した。

| 項目 | 値 |
| --- | --- |
| 元画像 | `20260720_135157.jpg` |
| 店名 | ガスト 天神橋筋六丁目店 |
| 利用日 | 2026-07-19 |
| 合計 | 2,701円 |
| 明細 | キッズうどんプレート 604円、担々うどん 999円、鉄板バーグ 769円、大ライス 329円 |

### VMの自動処理

`journalctl` で、timerによる次の処理順を確認した。

```text
{"status": "llm_pending", "driveFileId": "1TkfuQhiLXC2bMQo6fZKaqo2Y8i2DwzD6"}
{"status": "llm_completed", "driveFileId": "1TkfuQhiLXC2bMQo6fZKaqo2Y8i2DwzD6", "model": "gpt-5.6-luna"}
{"status": "needs_review", "driveFileId": "1TkfuQhiLXC2bMQo6fZKaqo2Y8i2DwzD6", "parseSource": "codex"}
```

`needs_review` は失敗ではなく、Web確認待ちへ正常に登録された状態である。

### Web確認・確定

- Web画面を再読み込み後、確認待ちに1件表示された。
- 店名、日付、支払者、合計、4明細、カテゴリ `食費 / 外食` が元レシートと一致した。
- 明細合計 `604 + 999 + 769 + 329 = 2,701円` とレシート合計の差額が0円であることを確認した。
- **確定する** を実行した。
- 確認待ちが0件になった。
- 取引一覧で4明細から「確認待ち」表示が消えた。
- 2026-07のホームで支出と食費がともに2,701円、日別支出が7月19日に表示された。

## 結果

合格。以下の一連を実運用構成で確認した。

```text
スマートフォン撮影画像
  -> Google Drive receipt-inbox-poc
  -> OCI I/O worker / Cloud Vision
  -> Codex LLM worker
  -> Firestore
  -> Web確認画面
  -> 手動確定
  -> 取引一覧・月次集計
```

## 次の受け入れ確認: 専用Androidアプリからの送信

専用アプリ「レシート撮影」で、設定画面の **Google Driveフォルダを選択** を開く。Google Pickerで通常の `receipt-inbox` ではなく **`receipt-inbox-poc`** を選択し、支払者名が正しいことを確認してからレシートを1枚撮影・送信する。

確認項目:

1. アプリが撮影画像を `receipt-inbox-poc` へ1枚だけアップロードする。
2. ファイル名またはアプリ設定から支払者が正しく引き継がれる。
3. VMログが `llm_pending`、`llm_completed`、`needs_review` または `confirmed` まで進む。
4. `needs_review` の場合はWebで内容を確認して確定し、当月の取引・ホーム集計へ反映される。

PoCの間は専用アプリの保存先を `receipt-inbox-poc` に保つ。通常運用用の `receipt-inbox` へ戻すのは、PoC VMの監視先と運用方針を切り替えるときに行う。

## 専用Androidアプリからの送信確認

専用Androidアプリ「レシート撮影」でGoogle Driveフォルダを選び直し、`receipt-inbox-poc` を選択した。アプリが作成した次の画像が、実際にPoCフォルダへ保存されたことをGoogle Driveで確認した。

```text
receipt__a2Vuamlybw__20260720T051636Z__6c889089-6dfa-4b49-9ddb-0c8f38d16623.jpg
```

Web確認画面では、次が正しく表示された。

- 店名: `PATISSERIE MIYOSHI`
- 日付: 2026-07-18
- 支払者: `kenjiro`
- 合計・明細: チョコバナナスムージー 500円
- カテゴリ: `食費 / 飲料`
- 差額: 0円

したがって、専用アプリからDriveのPoCフォルダ、OCI worker、Web確認画面までの経路は合格とする。Web上での確定と月次集計反映は、このレシートを確定後に確認する。

### 発見事項

アプリの設定画面は実際に `receipt-inbox-poc` を選択していても `保存先: receipt-inbox` と表示した。実アップロード先はPoCフォルダで正しかった。原因と修正要件は `docs/handover/2026-07-20_02_web_review_operations_improvements.md` に記録した。
