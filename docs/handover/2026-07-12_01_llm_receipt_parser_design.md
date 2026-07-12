# 引き継ぎ: LLMを使ったレシート解析版の設計検討

## 目的

現在の `receipt-ocr` は、OCI VM上でGoogle DriveのPoCフォルダを監視し、Google Cloud Vision APIでOCRし、Pythonのルールベースparserでレシート情報を抽出してFirestoreへ保存している。

ここまでのPoCで、Drive → Vision OCR → Firestore保存 → 重複防止 → CLI確認の流れは動作確認済み。ただし、レシートの書式差分をルールベースだけで吸収するのは非現実的になりつつある。

次セッションでは、LLMを使ったレシート解析版を設計する。

## 最重要制約

ユーザーはChatGPT Plusを契約済みだが、OpenAI APIの追加課金は避けたい。

そのため、初期設計では次を前提にする。

- OpenAI APIキーをOCI VMに置かない
- `openai` Python SDKを本番ワーカーに組み込まない
- OpenAI API課金が発生する自動処理は実装しない
- ChatGPT Plusの範囲で使えるものは、設計相談・手動解析・Codexによる開発支援に限定する

注意: ChatGPT Plusの契約は、OCI VMからOpenAI APIを自動呼び出しするための無料枠ではない。サーバー側で自動LLM解析をしたい場合は、通常はAPI課金、別サービスの無料枠、またはローカルLLMが必要になる。

## 現在のブランチ状況

LLM未使用版として、次のブランチを作成済み。

```text
codex/ocr-parser-no-llm
```

このブランチは、現時点のルールベースOCR解析版の保存地点。

LLM版を開発する場合は、`main` から新しいブランチを切る。

推奨ブランチ名:

```text
codex/ocr-parser-llm-design
```

または実装まで進める場合:

```text
codex/ocr-parser-llm-assisted
```

## 現在のPoC構成

```text
Google Drive receipt-inbox-poc
  -> OCI VM cloud-worker
  -> Google Cloud Vision API
  -> parse_receipt()
  -> categorize_items()
  -> reconcile_receipt()
  -> Firestore poc_ocr_jobs / poc_receipts
```

主要ファイル:

```text
src/receipt_ocr/cloud_worker.py
src/receipt_ocr/parser.py
src/receipt_ocr/reconciliation.py
src/receipt_ocr/firestore_writer.py
src/receipt_ocr/cli.py
tests/test_parser.py
tests/test_reconciliation.py
tests/test_cloud_worker.py
```

PoC結果の取得CLI:

```bash
sudo -u receipt-ocr /bin/bash -c '
  set -a
  source /etc/receipt-ocr-poc/config.env
  set +a
  exec /opt/receipt-ocr/.venv/bin/python \
    -m receipt_ocr \
    --config /etc/receipt-ocr-poc/config.json \
    cloud-worker receipt DRIVE_FILE_ID --poc
' | jq
```

## 現在Firestoreへ保存しているPoC結果

`households/{householdId}/poc_receipts/{driveFileId}` に保存する主なフィールド:

```text
driveFileId
shopName
purchasedAt
totalAmount
payer
status
reviewReason
difference
parsedItems
reconciledItems
createdAt
updatedAt
```

`parsedItems` はparser + categorizerの結果。
`reconciledItems` は値引き・税・端数調整などを追加した後の結果。

OCR全文とレシート画像はFirestoreへ保存していない。

## これまで確認した実例

### ABC-MART 領収証

修正後、以下は成功。

```text
shopName: ABC-MART
purchasedAt: 2026-05-03
totalAmount: 4389
status: confirmed
reviewReason: reconciled
```

対応した主な問題:

- カード売上票の `承認番号 224574` を合計金額として誤採用
- `日計金額 ¥4,389` を合計として扱う

### 松福堂 レシート

修正後、合計抽出は改善。

```text
purchasedAt: 2026-05-23
totalAmount: 1296
```

残課題:

- 店名OCR揺れ
- 外税や明細構造の扱い
- カテゴリ未分類

### 丸亀製麺 レシート

修正後、合計抽出は改善。

直近の期待値:

```text
purchasedAt: 2026-05-13
totalAmount: 920
```

明細例:

```text
かけ(大) 630
かしわ天 220
鮭おむすび 170
5枚天ぷら100円引 -100
合計 920
```

直近で対応したこと:

- `お釣り ¥10` を合計として誤採用しない
- `合 計 ¥920` を合計として扱う
- `100円引` / `円引` を値引き調整として扱う

残課題:

- `かしわ天 220` がOCR/行対応の都合で `鮭おむすび 220` になったケースあり
- 店名が `亀製麵 田` などに揺れる
- カテゴリ未分類が多い

## ルールベースの限界

ここまでで分かったこと:

- 合計金額だけでも、`合計`、`合 計`、`合言十`、`日計金額`、カード売上票、税行、支払行、お釣り行などの例外が多い
- 商品明細はさらに難しい
  - 商品名と金額が同じ行とは限らない
  - 単価、数量、小計、税、値引きが混ざる
  - OCRが商品名を落とす、または隣接行と対応付けを誤る
- 店名はロゴ・筆文字・住所・業種見出しが混じる

したがって、全レシートを逐一ルール追加で対応する方針は避ける。

## LLM版の設計方針

LLMを「正解を決める装置」として使わない。
LLMは「候補を作る装置」として使い、最終採用前にアプリ側で必ず検算する。

基本方針:

```text
Vision OCR
  -> ルールベース解析
  -> 合計一致・必須項目OK・カテゴリOKなら自動確定
  -> それ以外だけLLM補助
  -> LLM結果を検算
  -> 検算OKなら採用候補
  -> 検算NGならneeds_review
```

LLM出力の想定JSON:

```json
{
  "shopName": "丸亀製麺 イオンモール鶴見緑地",
  "purchasedAt": "2026-05-13",
  "totalAmount": 920,
  "items": [
    { "name": "かけ(大)", "amount": 630 },
    { "name": "かしわ天", "amount": 220 },
    { "name": "鮭おむすび", "amount": 170 },
    { "name": "5枚天ぷら100円引", "amount": -100 }
  ],
  "flags": ["discount_detected"]
}
```

検算:

```text
630 + 220 + 170 - 100 = 920
```

一致しない場合は採用しない。

## ChatGPT Plusだけでできる案

OpenAI API課金を使わない場合、完全自動のサーバー側LLM解析は難しい。

現実的な案は以下。

### 案A: 手動LLM補助

`needs_review` になったレシートについて、CLIでOCR解析結果・必要情報を出力し、ユーザーがChatGPT Plusへ貼り付ける。

ChatGPTがJSON候補を返し、それをCLIで取り込む。

メリット:

- OpenAI API課金なし
- ChatGPT Plusの範囲で試せる
- 解析プロンプトを詰めやすい

デメリット:

- 自動化されない
- 家計簿アプリとしては手間が残る

### 案B: PoC専用の手動評価ワークフロー

当面は自動処理に組み込まず、`needs_review` のOCRテキストをローカルVMまたはMacで確認し、ChatGPTに手動投入して精度評価する。

目的:

- LLMでどれくらい改善するかを見る
- どのJSON schemaがよいか決める
- 自動化する価値があるか判断する

### 案C: ローカルLLM

OCI Always Free VM上でローカルLLMを動かす案。

ただし、現在のVMはAmpere 1 OCPU / 6GB RAM構成。日本語OCRテキストから安定して構造化抽出する品質を期待するには厳しい可能性が高い。

初期候補としては推奨しない。

## OpenAI APIを使う場合の案

ユーザーの現在方針では採用しない。ただし、将来検討する場合の設計だけ残す。

APIを使うなら、`needs_review` のみOpenAI APIへ投げる。全件投入しない。

保存フィールド案:

```text
llmParsed
llmModel
llmPromptVersion
llmValidated
llmValidationErrors
```

採用条件:

- 必須項目がある
- `sum(items.amount) == totalAmount`
- 日付が妥当
- 金額が正の整数または値引きとして負の整数
- OCRテキストに存在しない極端な情報を作っていない

## 次セッションで最初にやること

1. `main` からLLM設計用ブランチを作る。

```bash
git switch main
git pull --ff-only origin main
git switch -c codex/ocr-parser-llm-design
```

2. まずはOpenAI APIを使わない前提で、手動LLM補助フローを設計する。

3. `needs_review` の対象について、CLIで次の情報を出せるようにする案を検討する。

```text
driveFileId
sourceName
shopName
purchasedAt
totalAmount
parsedItems
reconciledItems
difference
reviewReason
OCR全文（一時ローカルのみ。Firestoreへは保存しない）
```

4. ChatGPTへ貼るプロンプトと、返却JSON schemaを設計する。

5. JSONを取り込むCLIを設計する。

候補コマンド:

```bash
receipt-ocr cloud-worker export-review DRIVE_FILE_ID --poc
receipt-ocr cloud-worker import-llm-review DRIVE_FILE_ID result.json --poc
```

## 注意点

### OCR全文の扱い

当初方針では、OCR全文と画像はクラウドへ保存しない。

LLM検証ではOCR全文が必要になるが、Firestoreへ保存しない方針は維持する。

候補:

- VMローカルに短期間だけ保存
- 手動CLI出力で確認
- 検証後に削除

### 自動確定条件

LLMを入れても、いきなり全自動確定しない。

初期は以下にする。

```text
LLM結果が検算OK -> needs_review with llmParsed
人間が確認
```

十分な実績が出たら、一部だけ自動確定を検討する。

### コスト方針

現時点ではOpenAI API課金を使わない。

Cloud Vision APIは既にBilling有効化済みで、以下を設定済み。

```text
予算アラート: 100円
Visionクォータ: 20
POC_MAX_VISION_UNITS: 20
```

LLM版でも、追加の従量課金を増やさない設計を優先する。

## 現時点の結論

ルールベース版は、基盤PoCとしては成功。

ただし、実用的な家計簿OCRとしては、ルールベースだけでは保守負荷が高すぎる。

次は「ChatGPT Plusを使った手動LLM補助で、LLM解析の有効性を評価する」段階に進むのが妥当。

完全自動のLLM解析は、OpenAI API課金なしでは成立しにくい。まず手動LLM補助で効果を確認し、その結果を見て、API課金を許容するか、ローカルLLMを試すか、ルールベース継続にするか判断する。
