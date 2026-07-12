# Codex CLI全自動レシート解析 実装・運用引き継ぎ書

作成日: 2026-07-12

対象リポジトリ: `/Users/k-hirata/Documents/receipt-ocr`

対象VM: `receipt-ocr-vcn`（Oracle Linux 9 / ARM64）

## 1. 現在の結論

ChatGPT Plus認証のCodex CLIをOCI VM上で非対話実行し、レシートを全自動解析するPoCは実装と実機確認まで完了した。

確認済みの処理経路:

```text
Google Drive
  -> Cloud Vision OCR
  -> ローカルspool
  -> Codex CLI（ChatGPT認証、gpt-5.6-luna）
  -> JSON Schema検証・合計検算
  -> Firestore receipts / transactions
  -> Firebase HostingのWeb確認画面
```

通常処理にChatGPT画面への手動貼り付けは不要である。現在は3つのsystemd timerが有効で、Drive監視、Codex解析、認証health checkが自動実行される。

APIキー、OpenAI API従量課金、追加クレジットは使用していない。Codex専用ユーザーのChatGPT認証を使用している。

## 2. 2026-07-12終了時点の稼働状態

### VMとランタイム

| 項目 | 状態 |
| --- | --- |
| OS | Oracle Linux Server 9.8 |
| CPU architecture | `aarch64` |
| アプリ | `/opt/receipt-ocr` |
| 設定 | `/etc/receipt-ocr-poc/config.json` |
| 環境変数 | `/etc/receipt-ocr-poc/config.env` |
| spool | `/var/lib/receipt-ocr-poc/llm-spool` |
| I/O worker | `receipt-ocr` ユーザー |
| Codex worker | `receipt-ocr-codex` ユーザー |
| Codex CLI | 0.144.1、Linux ARM64 standalone版 |
| Codex認証 | ChatGPT認証、health check `ok` |
| Python | 3.9.25。動作するがEOL警告あり |

### systemd timer

次の3つはすべて `enabled`、`active` を確認済み。

| timer | 間隔 | service |
| --- | --- | --- |
| `receipt-ocr-poc.timer` | 約5分 | Drive、Vision、Firestore側処理 |
| `receipt-ocr-llm.timer` | 約1分 | Codex CLI解析 |
| `receipt-ocr-llm-health.timer` | 毎週月曜9時（JST） | ChatGPT認証確認・更新 |

2026-07-12 22:16 JST時点で次回実行時刻が表示され、自動起動も確認できた。

## 3. 実機で確認したCodex解析

### 成功したレシート

| 項目 | 値 |
| --- | --- |
| Drive file ID | `1yqTm7qnBkCY_zAvK-9PVLLSpVs0Y0R5m` |
| 元ファイル | `20260712_140529_03.jpg` |
| 使用モデル | `gpt-5.6-luna` |
| LLM worker結果 | `llm_completed` |
| 最終状態 | `needs_review` |
| parse source | `codex` |

LLM workerの成功ログ:

```json
{"status":"llm_completed","driveFileId":"1yqTm7qnBkCY_zAvK-9PVLLSpVs0Y0R5m","model":"gpt-5.6-luna"}
```

I/O workerの登録ログ:

```json
{"status":"needs_review","driveFileId":"1yqTm7qnBkCY_zAvK-9PVLLSpVs0Y0R5m","parseSource":"codex"}
```

`needs_review` は処理失敗ではない。Codexのsoft warningまたは低confidenceがあるため、誤登録を避けてWeb確認へ回した正常な結果である。

### Web画面

Firebase Hosting URLでGoogleログインし、家計簿の **確認** 画面を表示できた。

```text
https://diesel-ellipse-500009-u3.web.app
```

画面で次を確認した。

- 確認待ちが2件表示される
- 丸亀製麺の店名、日付、支払者、合計が表示される
- 今回の明細は `630 + 220 + 170 - 100 = 920` で差額0円
- 大・小カテゴリを編集できる
- 「下書き保存」「確定する」操作が表示される

スクリーンショット取得時点では確認バッジが2件で「確定する」ボタンが表示されていた。Webへのアクセスとデータ表示は確認済みだが、その画像時点では確定後の状態までは確認していない。

## 4. 実装済みの主な内容

- Cloud workerが画像、行番号付きOCR、rule候補、許可カテゴリをローカルspoolへ保存する。
- Codex workerをGoogle/Firebase鍵から分離したLinuxユーザーとsystemd serviceで実行する。
- `codex exec` を非対話、ephemeral、read-only sandbox、approvalなしで実行する。
- JSON Schema出力、未知キー、未知カテゴリ、日付、金額、件数、根拠行、合計一致をアプリ側でも検証する。
- Luna結果の検証不一致時だけTerraへ再投入する。
- 通信障害、timeout、Plus上限を自動待機・再試行する。
- LLMで救済できない場合は検算済みrule候補を採用し、それも不可ならWeb確認へ回す。
- Drive file IDをreceipt IDとして冪等化し、VisionとCodexの重複処理を防止する。
- FirestoreへOCR全文、画像、Codexの生結果を保存しない。
- Webへ未解決system alertと確認待ち件数を表示する。
- ChatGPT認証以外の`auth.json`とAPIキー環境変数をworker側で拒否する。

## 5. 当日発生した問題と修正

### Codex CLIインストール時の作業ディレクトリ

rootのホームから`sudo -u receipt-ocr-codex`でinstallerを実行すると、`/root`へ戻れず失敗した。

対処済み:

```bash
/bin/bash -c 'cd "$HOME" && curl -fsSL https://chatgpt.com/codex/install.sh | sh'
```

### LLM workerが`worker_unavailable`

`/etc/receipt-ocr-poc/config.json`の`poc.llm.enabled`が`false`だったことが原因。`true`へ変更後、health checkは`ok`になった。

### JSON Schemaの400エラー

1回目はitem amountの`not: {const: 0}`、2回目は`schemaVersion`の`const`に`type`がなかったため、Codexの構造化出力で`invalid_json_schema`になった。

対処済み:

- 0円拒否をJSON Schemaの`not`ではなくアプリ検証へ移した。
- `schemaVersion`へ`type: string`を追加した。
- `const`に`type`がない場合に失敗する回帰テストを追加した。
- 全56 Pythonテスト成功を確認した。

### Gitのdubious ownership

VMの`/opt/receipt-ocr`をrootから更新すると所有者が異なるためGitに拒否された。次の一時指定で更新できる。

```bash
sudo git -c safe.directory=/opt/receipt-ocr \
  -C /opt/receipt-ocr pull --ff-only
```

cloud-initの再実行時にも同じ問題が起きないよう修正済み。

## 6. 明日以降の最優先作業: Python 3.11移行

現在のPython 3.9.25でも処理は成功しているが、GoogleライブラリからEOL・非サポート警告が出る。これは現時点ではエラーではない。

OS標準の`python3`は変更せず、アプリのvenvだけPython 3.11へ移行する。詳細手順とロールバック方法は次を参照する。

- `docs/OCI_POC_WORKER_ACTIVATION.md` の「14. 既存VMをPython 3.11へ更新する」

再開時の順序:

1. VMで最新`main`をpullする。
2. `python3.11`、`python3.11-devel`、`python3.11-pip`をdnfで追加する。
3. timerを動かしたまま`.venv-py311`を別途作成する。
4. 新venvへプロジェクトをinstallし、全56テストを実行する。
5. テスト成功後だけtimerと実行中serviceを停止する。
6. 旧`.venv`を`.venv-py39-backup`へ移動し、新venvを`.venv`へ切り替える。
7. `receipt-ocr-llm-health.service`が`ok`になることを確認する。
8. 3つのtimerを`enable --now`で戻す。
9. PoC workerログからPython 3.9の警告が消えたことを確認する。

旧venvは動作確認が終わるまで削除しない。

## 7. Python移行後の確認

```bash
sudo -u receipt-ocr /opt/receipt-ocr/.venv/bin/python --version

sudo systemctl start receipt-ocr-llm-health.service

sudo systemctl is-active \
  receipt-ocr-poc.timer \
  receipt-ocr-llm.timer \
  receipt-ocr-llm-health.timer

sudo journalctl \
  -u receipt-ocr-poc.service \
  -u receipt-ocr-llm.service \
  --since "10 minutes ago" \
  --no-pager -o cat
```

期待値:

- `Python 3.11.x`
- health checkが`{"status":"ok"}`
- 3 timerがすべて`active`
- Python 3.9 EOL警告が出ない
- 空き状態では両workerが`idle`になる

## 8. 残作業・追加確認候補

優先度順:

1. Python 3.11へ移行する。
2. Webで今回の確認待ちレシートを確定し、確認バッジが減ることを確認する。
3. 確定後、`receipts.status=confirmed`、transactions明細、関連alert解決を確認する。
4. 新しいレシート1枚をDriveへ追加し、timerだけで最後まで処理されることを確認する。
5. Luna検証不一致からTerra再解析へ進む実機経路を確認する。
6. Plus上限、401、timeout、VM再起動後の回復はunit test済みだが、必要に応じて運用試験する。
7. 24時間はjournal、Firestore利用数、Vision利用数、system alertを観測する。

## 9. 運用上の注意

- 通常運用ではserviceを手動で連続起動しない。timerへ任せる。
- `needs_review`は正常な安全側の状態であり、LLM失敗とは限らない。
- Codex失敗後のcompleted jobをPoC workerが処理するとrule fallbackへ進む。エラー調査中は先に`error.json`を確認する。
- Codex認証失効時はAPIキーへ切り替えず、専用ユーザーでdevice loginをやり直す。
- `/var/lib/receipt-ocr-poc/llm-spool`の画像・OCRは機密情報として扱う。
- `auth.json`、OCR全文、画像、サービスアカウント鍵をGit、Firestore、journalへ出さない。
- Plus上限中は自動待機する。誤った自動登録より遅延・確認待ちを優先する。

## 10. 関連資料

- 設計書: `docs/design/2026-07-12_codex_cli_receipt_parser_design.md`
- 実装計画: `docs/plan/2026-07-12_codex_cli_receipt_parser_implementation_plan.md`
- VM手動設定・運用手順: `docs/OCI_POC_WORKER_ACTIVATION.md`
- OCI PoC初期確認ログ: `docs/operation-check/2026-07-12_oci-poc-worker.md`
- JSON Schema: `schema/receipt-llm-result-v1.json`

元の`docs/handover/2026-07-12_llm_receipt_parser_design.md`は変更していない。

## 11. 関連コミット

| commit | 内容 |
| --- | --- |
| `5129f42` | Codex CLI全自動解析の実装 |
| `0474acc` | 既存VMへのCodex導入対応、最初のSchema修正 |
| `1c7d053` | `schemaVersion`の型宣言修正 |
| `dd69d26` | Web確認とPython 3.11移行手順追加 |
| `322c497` | Python移行時の停止時間短縮 |
| `9ef98c3` | venv切替前のworker停止を追記 |

2026-07-12終了時点の`main`先頭は`9ef98c3`である。この引き継ぎ書を追加するコミットはその後に続く。
