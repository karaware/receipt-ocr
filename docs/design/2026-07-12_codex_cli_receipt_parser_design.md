# Codex CLIによる全自動レシート解析 設計書

作成日: 2026-07-12

対象: `receipt-ocr` OCI Cloud Vision PoCから正式家計簿への自動解析経路

ステータス: 実装済み（2026-07-12）

## 1. 結論

ChatGPT Plusで利用できるCodex CLIをOCI VMへ導入し、`codex exec` を非対話で実行する。人がChatGPTへOCR結果を貼り付けたり、返却JSONを手動で取り込んだりする運用は採用しない。

解析は次の全自動フローとする。

```text
Google Drive
  -> 既存cloud-worker
       -> 画像download
       -> Google Cloud Vision OCR
       -> rule candidate作成
       -> Codex用spoolへ画像・OCR・候補・カテゴリをenqueue
  -> Codex専用llm-worker
       -> codex exec + 画像 + OCR
       -> JSON Schema準拠の候補をspoolへ出力
  -> 既存cloud-worker
       -> JSONと業務ルールを検証
       -> 成功: receipts / transactionsへ自動登録
       -> 失敗: Terraで再解析
       -> 再失敗: rule candidateで自動救済
       -> 救済不可: needs_review + Web警告
```

通常のレシート処理は完全無人とする。許容する人の操作は次の3点だけである。

- 初回のChatGPT認証
- refresh token失効時の再認証
- 自動処理をすべて通過できなかった例外レシートのWeb修正

OpenAI APIキー、OpenAI API従量課金、追加Codexクレジットは使用しない。

## 2. 公式仕様上の実現可能性

2026-07-12時点で、採用に必要な機能は公式に案内されている。

| 必要機能 | 確認結果 |
| --- | --- |
| 非対話実行 | `codex exec` はscript、CI、scheduled job用として提供される |
| 構造化出力 | `--output-schema` と `--output-last-message` を併用できる |
| 画像入力 | Codex CLIの `--image` でローカル画像を渡せる |
| Plus認証 | Codex CLIはChatGPT subscription認証を利用できる |
| headless認証 | `codex login --device-auth` または `auth.json` の安全な転送を利用できる |
| 認証維持 | Codexが期限前と401発生時にtokenをrefreshし、`auth.json` を更新する |
| Linux | 公式installerはLinuxをサポートし、OCI A1用のaarch64 binaryを選択する |
| sandbox | Linuxではbubblewrapを使い、filesystemとcommand実行を制限できる |

根拠:

- [Codex非対話モード](https://learn.chatgpt.com/docs/non-interactive-mode)
- [ChatGPT管理認証をCI/CDで維持する方法](https://learn.chatgpt.com/docs/auth/ci-cd-auth)
- [Codex認証](https://learn.chatgpt.com/docs/auth)
- [Codex sandbox](https://learn.chatgpt.com/docs/sandboxing)
- [Codex料金と利用上限](https://chatgpt.com/codex/pricing/)

ただし、ChatGPT管理認証による自動処理は、API key認証より運用上の保証が弱い。refresh tokenの失効、Plus上限、モデル提供変更により一時停止する可能性を前提に設計する。

## 3. 目的と非対象

### 3.1 目的

- レシートごとのChatGPT手動操作をなくす。
- 画像レイアウトとVision OCRの両方をLLMへ与え、ルールparserの書式依存を減らす。
- LLM出力をSchemaとアプリ側検算で拘束し、誤登録を防ぐ。
- Plus上限や認証障害が発生しても、重複課金・重複OCR・データ消失を起こさない。
- 自動処理できない例外だけを既存Web確認画面へ集約する。

### 3.2 非対象

- OpenAI API keyによる実行
- ChatGPTブラウザ画面の自動操作
- ChatGPT TasksまたはCustom GPTをOCI workerとして利用する構成
- OCI VM上への画像対応ローカルLLM常駐
- LLMの自己申告confidenceだけによる自動確定
- LLMが新しい家計カテゴリを自由に作る機能
- OCR全文、画像、`auth.json` のFirestore保存

## 4. 現行構成と変更理由

現行 `CloudWorker._process()` は、1回のoneshot内で次を直列実行する。

```text
Drive download
  -> Vision OCR
  -> parse_receipt()
  -> categorize_items()
  -> reconcile_receipt()
  -> FirestoreWriter.complete()
  -> 一時画像削除
```

Codexを同じprocess・Unix userで実行すると、外部入力であるレシート内容を扱うagentから次の秘密情報が読める可能性がある。

- Drive service account key
- Vision service account key
- Firebase Admin SDK key
- ChatGPTの `auth.json`

このため、既存workerへ単純に `subprocess.run(["codex", "exec", ...])` を追加しない。秘密鍵を持つI/O workerと、Codexだけを実行するLLM workerを分離する。

## 5. 目標アーキテクチャ

### 5.1 I/O worker

既存の `receipt-ocr` userで動かす。次を担当する。

- Drive画像の列挙とdownload
- Vision利用予約とOCR
- rule candidateとrule reconciliationの生成
- Firestoreから許可カテゴリ一覧を取得
- LLM jobのenqueue
- Codex結果の検証
- 正式 `receipts / transactions` とPoC監査情報の保存
- Web用system alertの保存
- terminal jobのspool削除

Codex CLIとChatGPT認証情報へはアクセスしない。

### 5.2 LLM worker

新しい専用user `receipt-ocr-codex` で動かす。次だけを担当する。

- pending spoolから1件を取得
- ChatGPT管理認証で `codex exec` を実行
- JSON結果または分類済みerrorをcompleted spoolへ保存
- `auth.json` の自動refresh

次にはアクセスできない。

- `/etc/receipt-ocr-poc/secrets`
- Firestore
- Google Drive
- Google Cloud Vision
- `/opt/receipt-ocr` の書き込み

### 5.3 ローカルspool

```text
/var/lib/receipt-ocr-poc/llm-spool/
  pending/{driveFileId}/
  running/{driveFileId}/
  completed/{driveFileId}/
  unresolved/{driveFileId}/
```

job directory:

```text
job.json             # requestとretry/lease metadata
ocr.txt
source.<ext>
result.json         # LLM成功時
events.jsonl        # size制限したCodexイベント
error.json          # LLM失敗時
```

要件:

- `driveFileId` は許可文字を検証してからpathへ使う。
- enqueueは一時directoryへ書いた後のatomic renameで完成させる。
- `pending -> running` のrenameをjob lockとして使用する。
- 同時実行は1件だけとする。
- 完了したjobはFirestore commit後に削除する。
- `needs_review` のjobだけ `unresolved` へ移し、7日後に削除する。
- OCR全文や画像をsystemd journalへ出さない。

## 6. 処理シーケンス

### 6.1 新規レシートのenqueue

1. I/O workerが既存のFirestore reservationを取得する。
2. 画像をdownloadし、Vision開始前に既存どおり `visionAttempted=true` を保存する。
3. Vision OCRを1回だけ実行する。
4. 既存parser、categorizer、reconciliationを実行してrule candidateを保持する。
5. Firestoreの `categories` を読み、LLMが選択可能な大・小カテゴリ一覧を作る。
6. 画像、行番号付きOCR、rule candidate、カテゴリ一覧をspoolへenqueueする。
7. jobを `llm_pending` に更新し、download用一時画像を削除する。

Vision成功後にCodexが失敗しても、Visionを再実行しない。以後の再試行は同じspoolを使用する。

### 6.2 Codex解析

1. LLM workerが実行可能時刻を過ぎたpending jobを1件選ぶ。
2. directoryを `running` へatomic renameする。
3. Lunaで `codex exec` を実行する。
4. exit code、JSONL event、result fileを記録する。
5. processとして成功し、resultがJSONならcompletedへ移す。
6. process失敗ならerror分類と `nextAttemptAt` を書き、pendingへ戻すかcompletedへ送る。

LLM workerはLLM結果の業務検算やFirestore書き込みを行わない。

### 6.3 結果確定

I/O workerは毎回、新しいDrive画像を探す前にcompleted spoolを最大1件処理する。

1. `driveFileId`、input hash、schema versionを照合する。
2. JSON schemaと業務ルールを検証する。
3. Luna結果が不正なら、同じ入力をTerra用jobとして1回だけ再enqueueする。
4. 有効なら正式 `receipts / transactions` へ冪等に保存する。
5. PoC監査情報へparse source、model、prompt/schema version、warningを保存する。
6. Firestore commit成功後にspoolを削除する。

### 6.4 rule救済

Terraでも有効な結果が得られない場合、enqueue時に保存したrule candidateを使用する。

- rule reconciliationが `confirmed` なら `parseSource=rule_fallback` で自動登録する。
- rule reconciliationが `needs_review` なら正式collectionへ `needs_review` として登録する。
- `needs_review` はWeb確認一覧へ表示し、`llm_exhausted` alertを作る。

LLM失敗を理由に不完全なrule candidateを `confirmed` に昇格しない。

## 7. Codex CLI実行仕様

### 7.1 command

Python subprocessからshellを使わずargv配列で実行し、promptはstdinで渡す。

主処理:

```text
codex --ask-for-approval never exec
  --ephemeral
  --ignore-user-config
  --sandbox read-only
  --skip-git-repo-check
  --cd JOB_DIRECTORY
  --model gpt-5.6-luna
  --image JOB_DIRECTORY/source.jpg
  --output-schema /opt/receipt-ocr/schema/receipt-llm-result-v1.json
  --output-last-message JOB_DIRECTORY/result.json
  --json
  -
```

検算失敗時だけ `--model gpt-5.6-terra` へ変更する。

`--ignore-user-config` は、個人のMCP、plugin、web search、project instructionsが解析結果と使用量へ影響しないようにするために指定する。認証は `CODEX_HOME` から引き続き読み取られる。

### 7.2 sandbox

- `read-only` ではagentによる書き込みを禁止する。
- `approval=never` によりcommand実行や権限拡張を要求しても停止させる。
- `danger-full-access`、`workspace-write`、`--search` を使用しない。
- 作業directoryには対象jobの入力だけを置く。
- output fileへの書き込みはCodex clientの `--output-last-message` だけに限定する。

### 7.3 timeoutとresource

- Luna timeout: 180秒
- Terra timeout: 240秒
- systemd全体の `TimeoutStartSec`: 5分
- `MemoryMax`: 2GB
- `TasksMax`: 64
- timeout時はprocess groupを終了し、途中のresultを採用しない。

## 8. ChatGPT Plus認証

### 8.1 初期認証

方式は次の優先順とする。

1. OCI上で `codex login --device-auth` を実行し、別端末のbrowserでone-time codeを承認する。
2. device authが利用できない場合、信頼済みMacでfile-backed authを作り、`auth.json` を安全に転送する。

設定:

```toml
cli_auth_credentials_store = "file"
forced_login_method = "chatgpt"
```

配置:

```text
/var/lib/receipt-ocr-codex/.codex/auth.json
owner: receipt-ocr-codex
mode: 0600
```

`auth_mode` が `chatgpt` でrefresh tokenが存在することを確認する。API key認証ならworkerを起動しない。

### 8.2 自動refresh

- 永続 `CODEX_HOME` を使う。
- 同じ `auth.json` を複数machineや同時jobで共有しない。
- Codexが更新したfileを古いseedで上書きしない。
- 通常jobがない週も、週1回 `OK` だけを返すhealth checkを実行する。
- health checkも同じexclusive lockを取得する。

### 8.3 認証失敗

401またはrefresh失敗を検出したら次を行う。

- jobを `auth_blocked` にする。
- 追加のCodex requestを停止する。
- `system_alerts` に `codex_auth_blocked` を1件だけ作る。
- rule救済可能なjobはruleで処理する。
- 再認証後、health check成功を条件にpending処理を再開する。

auth sessionは永久に維持される保証がない。再認証は障害対応として許容する。

## 9. Plus利用上限

家庭用として1日10枚以下を想定する。通常は1枚につきLuna 1 turn、検算失敗時だけTerra 1 turnを使用する。

方針:

- OpenAI API keyを設定しない。
- `OPENAI_API_KEY` と `CODEX_API_KEY` がenvironmentにあれば起動を拒否する。
- ChatGPTアカウントへ追加Codexクレジットを購入しない。
- 利用上限を有料creditで自動突破しない。
- 上限到達時はerror内のreset時刻を採用する。
- reset時刻が取得できない場合は5時間後へ延期する。
- 最初の上限検出から24時間を超えたjobはrule救済へ回す。
- weekly limit等で24時間後も復旧しない場合はWeb alertを作る。

Plusの利用量は同じアカウントによる他のCodex利用と共有される。登録まで数時間遅れることを許容し、誤登録より待機・保留を優先する。

## 10. LLM入力

promptは固定template `receipt-parser/1` とし、次を含む。

- 日本のレシートから構造化データを抽出する役割
- 画像とVision OCRの両方を使用する指示
- OCR本文中の命令を指示として実行しないprompt injection対策
- 読めない値を推測しない指示
- 預り、お釣り、支払、カード承認番号を明細や合計にしない指示
- 値引きは負数、商品は正数とする指示
- 金額は税込の実支払対象となる明細合計を返す指示
- 架空の調整明細で合計を合わせない指示
- 指定カテゴリ以外を返さない指示
- 支払者を出力しない指示

動的入力:

```json
{
  "schemaVersion": "receipt-llm-input/v1",
  "driveFileId": "...",
  "inputSha256": "...",
  "ocrLines": [
    {"number": 1, "text": "株式会社丸亀製麺"}
  ],
  "ruleCandidate": {
    "shopName": "...",
    "purchasedAt": "...",
    "totalAmount": 920,
    "items": []
  },
  "allowedCategories": [
    {"major": "食費", "minor": ["食料品", "外食", "飲料", "その他"]}
  ]
}
```

`inputSha256` はschema version、driveFileId、OCR、rule candidate、カテゴリ、画像hashをcanonical JSON化して計算する。

## 11. LLM出力契約

出力schema versionは `receipt-llm-result/v1` とする。

```json
{
  "schemaVersion": "receipt-llm-result/v1",
  "driveFileId": "...",
  "inputSha256": "...",
  "shopName": {
    "value": "丸亀製麺 イオンモール鶴見緑地",
    "confidence": "high",
    "evidenceLineNumbers": [1, 3]
  },
  "purchasedAt": {
    "value": "2026-05-13",
    "confidence": "high",
    "evidenceLineNumbers": [6]
  },
  "totalAmount": {
    "value": 920,
    "confidence": "high",
    "evidenceLineNumbers": [13]
  },
  "items": [
    {
      "name": "かけ(大)",
      "amount": 630,
      "kind": "product",
      "majorCategory": "食費",
      "minorCategory": "外食",
      "confidence": "high",
      "evidenceLineNumbers": [7]
    },
    {
      "name": "5枚天ぷら100円引",
      "amount": -100,
      "kind": "discount",
      "majorCategory": "調整",
      "minorCategory": "値引き・税",
      "confidence": "high",
      "evidenceLineNumbers": [12]
    }
  ],
  "warnings": []
}
```

列挙値:

- `confidence`: `high | medium | low`
- `kind`: `product | discount | tax | fee | rounding`
- `additionalProperties`: 全objectで `false`

limits:

- item数: 1〜200
- item name: 1〜120文字
- shop name: 1〜120文字
- warnings: 最大20件、各200文字
- 金額絶対値: 1〜1,000,000円
- evidence line: inputに存在する行番号だけ

## 12. 検証

### 12.1 hard validation

1件でも違反した結果は採用しない。

- result fileがUTF-8 JSON objectである。
- sizeが64KB以下である。
- schema versionが一致する。
- 未知fieldがない。
- `driveFileId` と `inputSha256` がjobと一致する。
- 店名、日付、合計、明細が存在する。
- 日付が有効な `YYYY-MM-DD` で、2000年以降、JSTで翌日より未来ではない。
- totalが1〜1,000,000円である。
- item数が1〜200である。
- 0円明細がない。
- product、tax、feeは正数、discountは負数である。
- roundingの絶対値が10円以下で、OCR根拠がある。
- 大・小カテゴリがinputのallowlistに存在する。
- discount、tax、fee、roundingは大カテゴリ `調整` である。
- evidence行がinputに存在する。
- `sum(items.amount) == totalAmount` である。

### 12.2 soft warning

結果は採用できるが `needs_review` または監査対象にする。

- 必須fieldのconfidenceがlowである。
- rule candidateと日付または合計が異なる。
- 値が根拠行の正規化文字列から確認できない。
- imageからのみ読み取れ、OCR根拠行が空である。
- 同名同額の重複明細がある。
- warningが1件以上ある。

Phase 1ではsoft warningがある結果を `needs_review` とする。実績を評価した後、warning codeごとに自動確定可否を別ADRで決める。

## 13. retryとfailure分類

| failure | 動作 |
| --- | --- |
| timeout / network / 5xx | 5分、30分、2時間後に再試行 |
| Plus rate limit | reset時刻、なければ5時間後 |
| auth 401 / refresh failure | `auth_blocked`、再認証まで停止 |
| Luna resultのschema/検算不正 | Terraで即時1回再解析 |
| Terra resultも不正 | rule救済 |
| subprocess起動不可 | operational alert + rule救済 |
| Firestore write失敗 | completed spoolを残してI/O workerで再試行 |

同一modelへの一時障害retryは最大3回。LLM解析開始から24時間でdeadlineとし、それ以後はrule救済へ進む。

## 14. job状態

`poc_ocr_jobs.status` を次へ拡張する。

```text
discovered
  -> vision_reserved
  -> unknown_after_request
  -> llm_pending
  -> llm_running
  -> llm_retry_wait
  -> llm_completed
  -> confirmed
  -> needs_review

llm_running / llm_retry_wait
  -> auth_blocked
```

追加field:

```text
llmAttempted
llmAttempts
llmPrimaryModel
llmLastModel
llmPromptVersion
llmSchemaVersion
llmFirstAttemptAt
llmLastAttemptAt
llmNextAttemptAt
llmFailureCode
parseSource
```

`llm_running` のままVMが停止したjobは、lease期限15分を超えたら `llm_pending` へ戻す。result fileが完成している場合は再実行せずfinalizeする。

## 15. Firestore正式保存

### 15.1 receipt ID

正式 `receipts` document IDは `driveFileId` とする。既存documentがある場合は上書きせず、冪等成功とする。

### 15.2 receipts

既存fieldに次を追加する。

```text
source: "ocr"
parseSource: "codex" | "rule_fallback"
parserVersion
llmModel
llmPromptVersion
llmSchemaVersion
llmWarnings
```

OCR全文、画像、LLMの自由形式response、reasoning、event logは保存しない。

### 15.3 transactions

document IDは `{driveFileId}-{index:03d}` とする。LLMが返したallowed categoryを既存の `majorCategory / minorCategory` へ保存する。

receiptと最大200件のtransactionは同じFirestore batchでcreateする。途中成功を許さない。

### 15.4 PoC監査

`poc_receipts/{driveFileId}` にはrule candidate、採用source、検証warning、version情報を残す。画像、OCR、auth情報は残さない。

## 16. system alertsとWeb

collection:

```text
households/{householdId}/system_alerts/{alertId}
```

fields:

```json
{
  "code": "codex_auth_blocked",
  "severity": "error",
  "driveFileId": null,
  "message": "Codexの再認証が必要です",
  "createdAt": "SERVER_TIMESTAMP",
  "resolvedAt": null
}
```

alert code:

```text
codex_auth_blocked
codex_rate_limit_over_24h
codex_worker_unavailable
llm_exhausted
spool_cleanup_failed
```

同じcodeとdriveFileIdの未解決alertを重複作成しない。health checkやjob成功で原因が解消したalertは `resolvedAt` を設定する。

Web家計簿:

- top画面に未解決error/warning件数を表示する。
- alert一覧にcodeを日本語表示する。
- `llm_exhausted` から対象の既存receipt確認画面を開けるようにする。
- alert画面からOCR全文や画像は表示しない。
- `needs_review` の修正・確定処理は既存UIを再利用する。

## 17. configurationとCLI

設定案:

```json
{
  "poc": {
    "llm": {
      "enabled": false,
      "spool_dir": "/var/lib/receipt-ocr-poc/llm-spool",
      "primary_model": "gpt-5.6-luna",
      "retry_model": "gpt-5.6-terra",
      "primary_timeout_seconds": 180,
      "retry_timeout_seconds": 240,
      "deadline_hours": 24,
      "unresolved_retention_days": 7,
      "prompt_version": "receipt-parser/1",
      "schema_version": "receipt-llm-result/v1"
    }
  }
}
```

環境変数:

```text
CODEX_HOME=/var/lib/receipt-ocr-codex/.codex
RECEIPT_OCR_LLM_SPOOL=/var/lib/receipt-ocr-poc/llm-spool
```

CLI:

```text
receipt-ocr llm-worker --once
receipt-ocr llm-worker --dry-run
receipt-ocr llm-worker status
receipt-ocr llm-worker auth-status
receipt-ocr llm-worker health-check
receipt-ocr llm-worker cleanup
```

`cloud-worker --once` は先にcompleted LLM jobを最大4件finalizeし、その後に新規Drive画像を最大4件enqueueする。件数は `poc.max_images_per_run`（既定4）で変更できる。

## 18. systemd

追加unit:

```text
receipt-ocr-llm.service
receipt-ocr-llm.timer
receipt-ocr-llm-health.service
receipt-ocr-llm-health.timer
```

LLM timerは1分間隔、health timerは週1回とする。

LLM service hardening:

```text
User=receipt-ocr-codex
Group=receipt-ocr-codex
PrivateTmp=true
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateDevices=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictSUIDSGID=true
LockPersonality=true
MemoryMax=2G
TasksMax=64
TimeoutStartSec=5min
UMask=0077
```

書き込み許可はCodex state directory、running job、completed出力だけに限定する。Google/Firebase secrets directoryは `InaccessiblePaths` でも明示的に遮断する。

I/O workerとLLM workerがspoolを共有するため、専用groupとsetgid directoryを用いる。ただし各userの秘密directoryは共有groupから読めないmodeにする。

## 19. プライバシー

- ChatGPTのData Controlsでモデル改善への利用を無効にする。
- 画像とOCR文字列がOpenAIへ送信されることを運用前提として明記する。
- promptにはpayer、Google/Firebase credential、内部pathを含めない。
- OCR全文と画像はローカルspoolにだけ保持する。
- confirmed時は即削除、needs_review時は7日で削除する。
- Codex eventのreasoningをFirestoreへ保存しない。
- logはerror code、model、elapsed time、attempt numberだけを記録する。

## 20. 代替案

### 20.1 OpenAI API

最も標準的なserver-side automationであり、service account的なAPI key管理と明確な従量制御ができる。ただしChatGPT Plusと別課金になるため不採用。

### 20.2 ローカルLLM

認証や外部送信は不要になるが、現在のOCI A1 1 OCPU / 6GBで日本語レシート画像を安定解析する品質と速度を得るのは困難。OCR text専用の小型modelもCodexとの差を評価できる品質に達する保証がないため初期案では不採用。

### 20.3 ChatGPT browser automation

browser session、UI、DOM、認証に依存し、正式なstructured server interfaceではない。画面変更やMFAで停止し、出力schemaもCLIほど強制できないため不採用。

### 20.4 ChatGPT Tasks / Custom GPT

ChatGPT内のscheduled taskやGPTは、OCI上のprivate spoolを継続監視するworker interfaceではない。Drive、Vision、Firestoreを現在のservice account境界のまま統合できないため不採用。

### 20.5 Codex CLI + Plus

公式のnon-interactive mode、image input、JSON Schema、headless login、認証refresh手順を利用できる。利用上限と再認証の運用リスクはあるが、追加API課金なしで今回の自動化要件を満たすため採用。

## 21. テスト

### 21.1 unit test

- input hashのcanonical化と再現性
- output schemaの全fieldと上限値
- unknown field、unknown category、invalid dateの拒否
- item符号、件数、金額上限の境界値
- 明細合計とtotalの一致
- evidence lineの存在確認
- Luna不正時のTerra再enqueue
- retry時刻、24時間deadline、rule救済
- job lease回収と冪等処理
- alert重複防止と自動resolve

### 21.2 integration test

- Drive/Vision成功後に `llm_pending` になる。
- Codex再試行でVisionを再呼び出ししない。
- Luna成功で正式receiptとtransactionsが1batchで作成される。
- Luna不正、Terra成功でTerra結果が採用される。
- 両model不正、rule confirmedでrule結果が採用される。
- 両model不正、rule needs_reviewでWeb確認対象になる。
- rate limit、401、network、timeout、VM restartを再現する。
- Firestore失敗時にcompleted spoolが残る。
- 同一job再実行でreceiptやtransactionsが重複しない。

### 21.3 security test

- `receipt-ocr-codex` userから `/etc/receipt-ocr-poc/secrets` を読めない。
- Codexのshell command要求が `read-only + never` で実行されない。
- API key environmentがあるとserviceがfail closedする。
- OCR、画像、`auth.json` がFirestore、journal、Gitへ出ない。
- spoolのpath traversalとsymlinkを拒否する。

### 21.4 golden receipt

最初に次の既存実例をfixture化する。

- ABC-MART: 日計金額4,389円、承認番号を合計にしない。
- 松福堂: 外税と複数数量を扱い、合計1,296円。
- 丸亀製麺: 3商品と100円引きで合計920円、お釣りを除外。

店名、日付、合計、明細金額、値引き、カテゴリを人間正解JSONと比較する。

## 22. rollout

### Phase 0: offline evaluation

- schema、prompt、validator、Codex subprocess adapterを実装する。
- Macまたは隔離したOCI directoryで3 fixtureを解析する。
- Firestoreへ書かず結果を比較する。

### Phase 1: shadow mode

- 全対象をCodex解析するが、正式collectionには既存rule結果だけを書く。
- Codex結果をPoC監査情報で比較する。
- 20〜30枚で精度とPlus使用量を測る。

### Phase 2: primary mode

- hard validation成功かつsoft warningなしを自動確定する。
- soft warningまたは救済失敗だけをneeds_reviewにする。
- system alertとWeb表示を有効にする。

### Phase 3: 運用評価

- 1日10枚以下で通常数時間以内に処理されることを確認する。
- rate limit、認証更新、Web例外件数を1か月観測する。
- 自動確定条件の変更は実績に基づく別ADRで行う。

## 23. 受入条件

- レシートごとのChatGPT手動操作がない。
- ChatGPT管理認証 `auth_mode=chatgpt` だけを使用する。
- OCIにOpenAI API keyを配置しない。
- Plus上限時に課金へ切り替わらず、自動待機またはrule救済する。
- Vision呼び出し回数と既存上限管理が壊れていない。
- LLM不正JSONや合計不一致を自動確定しない。
- ABC-MART、松福堂、丸亀製麺の期待値を満たす。
- 同一Drive fileを複数回登録しない。
- 正常結果が正式家計簿へ自動登録される。
- 最終例外がWebに通知され、既存画面で修正できる。
- Google/Firebase keys、Codex auth、OCR全文、画像が意図しない保存先へ出ない。
- 既存rule版のunit testがすべて通る。

## 24. 実装順序

1. LLM input/output contract、schema、validatorを実装する。
2. atomic spoolとjob stateを実装する。
3. Codex subprocess adapterとLuna/Terra retryを実装する。
4. LLM専用user、systemd unit、bubblewrap、認証維持を構築する。
5. I/O workerへenqueueとfinalizeを追加する。
6. 正式Firestore publisherとsystem alertsを追加する。
7. Webへalert表示とneeds_review導線を追加する。
8. golden test、障害test、security testを実施する。
9. shadow modeで評価後、primary modeを有効化する。

この順序では、契約と検算を先に固定し、Codex出力が安全に扱えることを確認してから外部サービスと正式家計簿を接続する。
