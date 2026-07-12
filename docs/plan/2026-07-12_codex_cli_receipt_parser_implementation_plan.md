# Codex CLIによる全自動レシート解析 実装プラン

承認日: 2026-07-12

設計書: [Codex CLIによる全自動レシート解析 設計書](../design/2026-07-12_codex_cli_receipt_parser_design.md)

## 方針

- 元の引き継ぎ書は変更しない。
- ChatGPT Plus認証のCodex CLIをOCI Linux上で非対話実行する。
- 通常処理は完全自動とし、初回認証、認証失効時の復旧、最終例外のWeb修正だけを運用作業として許容する。
- OpenAI API key、API従量課金、追加Codexクレジットは使用しない。
- 画像とVision OCRをCodexへ渡し、Lunaを主系、検算失敗時のみTerraで再解析する。
- Codex障害時は自動再試行し、最終的に既存rule candidateで救済する。

## 実装順序

1. LLM input/output contract、JSON Schema、validatorを実装する。
2. atomic spool、job state、retry/deadlineを実装する。
3. Codex subprocess adapterと専用 `llm-worker` CLIを実装する。
4. cloud-workerへenqueue、result finalize、rule fallback、正式Firestore publishを追加する。
5. system alertsとWeb警告表示を追加する。
6. Codex専用user、bubblewrap、systemd service/timer、認証health checkをOCI deploymentへ追加する。
7. unit/integration/security/Webテストを追加し、既存テストとbuildを実行する。

## 公開インターフェース

- CLI:
  - `receipt-ocr llm-worker --once`
  - `receipt-ocr llm-worker --dry-run`
  - `receipt-ocr llm-worker status`
  - `receipt-ocr llm-worker auth-status`
  - `receipt-ocr llm-worker health-check`
  - `receipt-ocr llm-worker cleanup`
- job state:
  - `llm_pending`
  - `llm_running`
  - `llm_retry_wait`
  - `llm_completed`
  - `auth_blocked`
- parse source:
  - `codex`
  - `rule_fallback`
- LLM schema:
  - `receipt-llm-input/v1`
  - `receipt-llm-result/v1`

## 検証とfallback

- schema、file ID、input hash、日付、金額、カテゴリ、符号、evidence、明細合計をhard validationする。
- Lunaの構造不正・検算不一致はTerraで1回再解析する。
- timeout/network/5xxは5分、30分、2時間後に再試行する。
- Plus上限はreset時刻、取得不能なら5時間後に再試行し、24時間でrule fallbackへ移る。
- 認証失敗は `auth_blocked` とし、追加のCodex requestを止める。
- rule candidateがconfirmedなら自動採用し、それ以外はneeds_reviewとWeb alertにする。

## セキュリティ

- CodexはGoogle/Firebase secretsを読めない専用Unix userで動かす。
- `codex --ask-for-approval never exec` の順序で実行し、`--sandbox read-only --ephemeral --ignore-user-config` を固定する。
- promptはstdin、resultはJSON Schema付きoutput fileで受け取る。
- `auth.json` は専用永続 `CODEX_HOME` に0600で保存し、同時実行を1件にする。
- OCR、画像、auth、自由形式LLM responseをFirestoreやjournalへ保存しない。

## テストと受入条件

- ABC-MART、松福堂、丸亀製麺で店名、日付、合計、明細、値引き、カテゴリを検証する。
- Luna成功、Terra retry、rule fallback、最終needs_reviewをテストする。
- rate limit、401、network、timeout、VM再起動、同一job再実行をテストする。
- Codex userから秘密鍵を読めず、shellが実行されないことを確認する。
- 正常結果が正式 `receipts / transactions` へ冪等に登録されることを確認する。
- 既存rule版、Web、Androidのテストとbuildが回帰しないことを確認する。
