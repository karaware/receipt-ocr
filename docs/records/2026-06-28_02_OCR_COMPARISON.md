

# OCR比較メモ: Apple Vision OCR vs Google Cloud Vision API OCR

作成日: 2026-06-28

文書種別: 比較記録

## 目的

家計簿入力のために、レシート画像から以下の情報を自動抽出したい。

- 日付
- 店名
- 合計金額
- 支払い方法
- 必要に応じてカテゴリ

最終目標は「レシートを撮影したら、可能な限り自動で家計簿CSVまたはGoogleスプレッドシートに追記される」状態にすること。

## 前提

- 無料で運用したい
- ChatGPT Plusは契約済みなので、設計相談やCodex利用には使ってよい
- ただし、日常運用でChatGPTに手動添付する方式は採用しない
- MacBookがある
- ローカル自動化、ヘッドレス実行を重視する
- レシート画像には購買情報や支払い情報が含まれるため、できれば外部送信は避けたい

## 比較対象

1. Apple Vision OCR
2. Google Cloud Vision API OCR

## 比較表

| 観点 | Apple Vision OCR | Google Cloud Vision API OCR |
|---|---|---|
| 実行場所 | Macローカル | Google Cloud |
| 料金 | 追加費用なし | `DOCUMENT_TEXT_DETECTION` は毎月最初の1,000請求対象ユニットが無料。超過時は課金 |
| 課金事故リスク | なし | あり |
| APIキー・認証 | 不要 | 必要 |
| 日本語対応 | あり | あり |
| レシートのような密な文字 | 使える可能性が高い | より強い可能性が高い |
| 斜め・暗い・印字が薄い画像 | 撮影品質に左右されやすい | 比較的粘る可能性がある |
| レイアウト構造の取得 | ある程度可能 | block / paragraph / word など構造情報が豊富 |
| 個人情報・購買情報の外部送信 | なし | あり |
| 自動化のしやすさ | Swift CLIを作ればシンプル | 認証、API、課金管理が必要 |
| 家計簿MVP向き | とても向いている | 比較用・フォールバック向き |

### Google Cloud Visionの料金根拠

2026-06-28にGoogle Cloud公式資料を確認した。

- [Cloud Visionの料金（Google Cloud公式）](https://cloud.google.com/vision/pricing?hl=ja)
- [画像内のテキストを検出・抽出する（Google Cloud公式）](https://cloud.google.com/vision/docs/ocr?hl=ja)

公式料金表では、画像に適用する機能ごとに1つの請求対象ユニットとして数え、毎月最初の
1,000ユニットは無料とされている。`TEXT_DETECTION` と `DOCUMENT_TEXT_DETECTION` は、
どちらもこの無料枠の対象である。

この比較案のように、1枚のJPEG画像へ `DOCUMENT_TEXT_DETECTION` だけを1回適用する場合は、
原則として1画像が1ユニットに相当する。そのため「月1,000枚程度まで無料」と表現できるが、
正確には「月1,000請求対象ユニットまで無料」である。

注意点:

- 同じ画像へ複数の機能を適用すると、機能ごとに別ユニットとして数えられる。
- PDFなどの複数ページファイルは、各ページが個別の画像として扱われる。
- Vision API以外にCloud StorageやCompute Engineなどを使えば、別途費用が発生する可能性がある。
- 料金と無料枠は変更される可能性があるため、導入時に公式料金表を再確認する。

## 精度の見立て

精度だけを見れば、Google Cloud Vision API OCRの方が有利になる可能性が高い。

特に以下のようなレシートでは、Google Cloud Vision APIの方が強い可能性がある。

- 文字が密集している
- レシートが長い
- 斜めに撮影されている
- 印字が薄い
- 店舗ごとのレイアウト差が大きい
- 品目単位まで読みたい

一方で、家計簿用途でまず必要なのは、必ずしも品目単位の完全な読み取りではない。

最初に必要なのは以下の4項目。

- 日付
- 店名
- 合計金額
- 支払い方法

この範囲であれば、Apple Vision OCRでも十分に実用になる可能性が高い。

## 運用観点での重要ポイント

家計簿自動化では、最高精度よりも以下の価値が大きい。

- 無料で続けられる
- 課金事故がない
- ローカルで完結する
- APIキー管理が不要
- 毎日壊れず動く
- レシート画像を外部に送らない

この観点では、Apple Vision OCRがかなり有利。

## 推奨方針

最初からGoogle Cloud Vision APIを本命にするのではなく、以下の構成がよい。

```text
通常処理:
Apple Vision OCR

失敗時のみ:
Google Cloud Vision API OCR

それでも失敗した場合:
review/ フォルダに移動して手確認
```

つまり、全レシートをGoogle Cloudへ送るのではなく、Apple Vision OCRで抽出できなかったものだけGoogle Cloud Vision APIにフォールバックする。

## 推奨アーキテクチャ

```text
スマホでレシート撮影
↓
iCloud Drive / Google Drive / Syncthing などでMacに同期
↓
Mac側のinput/フォルダに画像が入る
↓
launchd または定期実行スクリプトで処理開始
↓
Apple Vision OCRでOCR
↓
日付・店名・合計金額・支払い方法を抽出
↓
抽出成功なら receipts.csv に追記
↓
Apple Visionで失敗したものだけ Google Cloud Vision API OCR
↓
それでも失敗したら review/ に移動
```

## ディレクトリ構成案

```text
receipt-ocr/
  input/
    レシート画像を置く
  processed/
    処理成功済み画像
  review/
    要確認画像
  ocr_text/
    apple/
      Apple Vision OCRの生テキスト
    google/
      Google Cloud Vision API OCRの生テキスト
  data/
    receipts.csv
    processed_hashes.json
  scripts/
    ocr_apple.swift
    ocr_google.py
    parse_receipt.py
    run.sh
  docs/
    records/
      2026-06-28_02_OCR_COMPARISON.md
```

## CSV形式案

```csv
date,store,total,payment_method,category,ocr_engine,status,image_file,memo
2026-06-28,ライフ,2380,クレジット,食費,apple,ok,IMG_001.jpg,
2026-06-28,スギ薬局,980,PayPay,日用品,google,ok,IMG_002.jpg,apple_failed
2026-06-28,不明,,不明,その他,none,need_review,IMG_003.jpg,total_not_found
```

## ベンチマーク方法

実際のレシート20〜30枚で比較する。

サンプル内訳の例:

- スーパー: 10枚
- ドラッグストア: 5枚
- コンビニ: 5枚
- 外食: 5枚
- その他: 5枚

評価項目:

- 日付が正しいか
- 店名が正しいか
- 合計金額が正しいか
- 支払い方法が取れたか

最初から品目単位の正確性は評価しない。

品目単位まで含めると、税率、割引、ポイント利用、クーポン、電子マネー明細などで難易度が急に上がるため。

## 比較結果CSV案

```csv
image_file,apple_date,google_date,apple_store,google_store,apple_total,google_total,apple_payment,google_payment,apple_ok,google_ok,winner,memo
IMG_001.jpg,2026-06-28,2026-06-28,ライフ,ライフ,2380,2380,クレジット,クレジット,true,true,both,
IMG_002.jpg,,2026-06-28,スギ薬局,スギ薬局,,980,,PayPay,false,true,google,apple_total_failed
```

## Codexに依頼するプロンプト案

```text
Macローカルで、Apple Vision OCR と Google Cloud Vision API OCR の精度比較ツールを作ってください。

目的:
日本語レシート画像から、日付・店名・合計金額・支払い方法を抽出し、Apple Vision OCR と Google Cloud Vision API OCR の結果を比較する。

要件:
- input/ フォルダ内の jpg, jpeg, png, heic を処理する
- Apple Vision OCR は Swift CLI で実装する
- Google Cloud Vision API は Python から DOCUMENT_TEXT_DETECTION を呼び出す
- Google Cloud Vision API は任意機能にし、認証情報がない場合はスキップする
- OCR結果の生テキストを ocr_text/apple/ と ocr_text/google/ に保存する
- OCRテキストから Python で以下を抽出する
  - 日付
  - 店名
  - 合計金額
  - 支払い方法
- 比較結果を comparison.csv に出力する
- Appleだけ成功、Googleだけ成功、両方成功、両方失敗が分かるようにする
- READMEにセットアップ手順を書く
- macOSで動くこと
```

## 最終判断

現時点の方針は以下。

```text
第1候補:
Apple Vision OCR

理由:
- 無料
- Macローカルで完結
- 課金事故なし
- APIキー不要
- レシート画像を外に出さない

第2候補:
Google Cloud Vision API OCR

使いどころ:
- Apple Vision OCRで失敗した画像だけフォールバック
- 精度比較のベンチマーク
- 品目単位の読み取りを検討する段階
```

まずは Apple Vision OCR だけでMVPを作る。

その後、失敗率が高い場合だけ Google Cloud Vision API OCR を追加する。
