# receipt-ocr の課金状況

- 更新日: 2026-07-20
- 対象: `receipt-ocr` の Firebase / Google Cloud Vision / OCI 構成
- この文書の目的: 月額の固定費と従量課金の条件を区別し、課金を確認・抑制する手順を残す。

## 結論

現在の想定利用量では、月額は **0 円** と見込む。

Firebase が Blaze（従量課金）プランであっても、プラン自体に月額固定料金はない。無料枠を超過した
リソースだけが課金される。Cloud Vision OCR も毎月最初の 1,000 ユニットは無料であり、現行の
PoC 上限 20 ユニットはこの範囲に収まる。

ただし、このリポジトリだけから Google Cloud の請求レポートや当月の実使用量は読めない。確定額は
Google Cloud Console の請求レポートで確認すること。

## 現在の構成と把握できている状態

| 項目 | 現在の状態 | 課金への意味 |
| --- | --- | --- |
| Firebase | Blaze へ移行済み（利用者申告） | 移行そのものの固定費はない。無料枠超過分は請求対象。 |
| Cloud Vision API | `DOCUMENT_TEXT_DETECTION` を 1 画像につき 1 回実行 | Billing の有効化が必要。最初の 1,000 ユニット/月は無料。 |
| Vision のアプリ側上限 | `POC_MAX_VISION_UNITS=20` | PoC 中の OCR を最大 20 回に制限する。 |
| Google Cloud 予算アラート | 100 円 | 通知のみ。課金や API 呼び出しを自動停止しない。 |
| OCR ワーカー | OCI Always Free VM | Always Free 枠の範囲で運用する前提。Cloud Vision の料金とは別。 |
| 画像保存 | Google Drive | Firebase Storage を画像保存先として使わない。 |
| 実行基盤 | Cloud Functions / Cloud Run は使わない | Firebase / Google Cloud 上の実行時間課金を増やさない。 |

過去の `docs/FIREBASE_GUIDE.md` などにある「Spark のまま使う」は初期方針であり、現在の Blaze 状態を
示すものではない。

## 月額見積もり

### Firebase

Blaze は「使った分だけ支払う」プランであり、基本料金はない。家計簿で使う Google ログイン、
Firestore、Firebase Hosting は、次の無料枠に収まる限り 0 円である。

| サービス | 無料枠 | このアプリでの見込み |
| --- | --- | --- |
| Firestore 保存容量 | 1 GiB | 家計簿データのみを保存するため、家庭利用では十分余裕がある。 |
| Firestore 読み取り | 50,000 件/日 | 2 人が家計簿画面を使う程度なら大幅に下回る見込み。 |
| Firestore 書き込み | 20,000 件/日 | OCR 1 件ごとの登録を含めても大幅に下回る見込み。 |
| Firebase Hosting 保存 | 10 GB | 静的な React アプリのため小さい。 |
| Firebase Hosting 転送 | 360 MB/日 | 家庭内の閲覧では通常無料枠内。 |

Google ログイン（電話 SMS 認証ではない）は、この用途では追加料金を想定しない。

### Cloud Vision OCR

実装は `document_text_detection`（Document Text Detection）だけを呼び出す。各画像は 1 請求対象
ユニットであり、PDF で複数ページを処理する場合はページごとに 1 ユニットとなる。

| 月間 OCR ユニット | Vision OCR 料金（USD） |
| ---: | ---: |
| 20（PoC 上限） | $0 |
| 100 | $0 |
| 1,000 | $0 |
| 2,000 | $1.50 |
| 10,000 | $13.50 |

1,001〜5,000,000 ユニットの単価は **$1.50 / 1,000 ユニット**、すなわち無料枠超過分 1 枚あたり
**$0.0015**。月間 `N` ユニット（`N > 1,000`）の概算は次のとおり。

```text
料金（USD） = (N - 1,000) × 0.0015
```

同じ Google Cloud プロジェクトで他の Vision 機能を使う場合、それらの利用分もサービスごとに集計される。
この見積もりは `DOCUMENT_TEXT_DETECTION` だけを使う本アプリ分である。

## 想定外の費用が出る条件

- Firestore、Hosting、Cloud Storage の無料枠を超える。
- Firebase Storage に画像を保存するよう変更する。
- Cloud Functions、Cloud Run、BigQuery、Artifact Registry などの Google Cloud サービスを追加する。
- Vision OCR の呼び出し上限を増やす、または重複処理の防止が壊れる。
- OCI で Always Free 対象外の VM、ボリューム、ネットワーク等を作成する。
- OpenAI API をサーバー側の自動処理に追加する（現在の設計では使用しない）。

## 毎月の確認手順

1. Google Cloud Console で Vision API を使うプロジェクトを選ぶ。
2. **お支払い → レポート** を開き、期間を当月にしてサービス別の費用を確認する。
3. Cloud Vision API、Firestore、Cloud Storage、Cloud Run / Functions に想定外の費用がないか確認する。
4. **お支払い → 予算とアラート** で、`receipt-ocr-vision-poc` の 100 円アラートが有効であることを確認する。
5. Firestore の `poc_ocr_usage` とジョブ数を確認し、Vision 利用数が想定どおりか確認する。

予算アラートは停止装置ではない。上限管理は月次の `POC_MAX_VISION_UNITS=800`、低い Vision クォータ、
重複 OCR を避けるジョブ状態管理を組み合わせて行う。

## 公式料金・運用情報

- [Firebase 料金表](https://firebase.google.com/pricing?hl=ja)
- [Cloud Firestore の課金](https://firebase.google.com/docs/firestore/pricing?hl=ja)
- [Cloud Vision API の料金](https://cloud.google.com/vision/pricing?hl=ja)
- [Cloud Billing の予算と予算アラート](https://cloud.google.com/billing/docs/how-to/budgets?hl=ja)

料金や無料枠は変更され得るため、構成を変更する前と請求が発生したときは必ず公式料金表を再確認する。
