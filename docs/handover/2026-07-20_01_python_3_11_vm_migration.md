# OCI VM Python 3.11移行 引き継ぎ

作成日: 2026-07-20

対象VM: `receipt-ocr-vcn`（Oracle Linux 9 / ARM64）

## 結論

OCI PoCワーカーのアプリ用Python venvをPython 3.9からPython 3.11.13へ移行し、稼働確認まで完了した。
OS標準の`python3`は変更していない。

確認済みの状態:

- `/opt/receipt-ocr/.venv/bin/python --version` は `Python 3.11.13`
- 新venvで `unittest discover -s /opt/receipt-ocr/tests` を実行し、56テストが成功
- `receipt-ocr-llm-health.service` は `Result=success`、`ExecMainStatus=0`
- `receipt-ocr-poc.timer`、`receipt-ocr-llm.timer`、`receipt-ocr-llm-health.timer` はすべて `active`
- I/O workerとLLM workerを新venvで1回ずつ実行し、どちらも `{"status": "idle"}`
- Python 3.9のEOL警告は新venvでの実行ログに出ていない

旧環境はロールバック用に次の場所へ保持している。問題なく運用できることを確認するまで削除しない。

```text
/opt/receipt-ocr/.venv-py39-backup
```

## 実施内容

1. VMの`main`を最新化した。
2. `/opt/receipt-ocr/.git/objects` にroot所有のファイルがあり、`receipt-ocr`ユーザーで`git pull`できなかったため、`/opt/receipt-ocr`を`receipt-ocr:receipt-ocr`へ戻した。
3. `python3.11`、`python3.11-devel`、`python3.11-pip`を導入した。
4. `/opt/receipt-ocr/.venv-py311`を作成し、依存関係を導入して全テストを実行した。
5. 3つのtimerと関連serviceを停止後、旧`.venv`を`.venv-py39-backup`へ退避し、新venvを`.venv`へ切り替えた。
6. health check成功後、3つのtimerを再有効化した。

## timer再有効化時の注意

I/O workerとLLM workerのtimerはそれぞれ`OnUnitActiveSec=5min`と`OnUnitActiveSec=1min`を使う。
timerを停止・再有効化した直後は、対象serviceの最終起動時刻が過去となり、timerは`active (elapsed)`でも
`NEXT=n/a`になることがある。

再有効化後は必ず次を実行する。

```bash
sudo systemctl start receipt-ocr-poc.service
sudo systemctl start receipt-ocr-llm.service

sudo systemctl list-timers --all \
  receipt-ocr-poc.timer \
  receipt-ocr-llm.timer \
  receipt-ocr-llm-health.timer
```

I/O workerとLLM workerの`NEXT`に、それぞれ約5分後・約1分後の時刻が表示されれば再スケジュール済みである。
この手動起動は通常の定期実行を前倒しするだけであり、未処理Drive画像があれば通常どおり処理される。

## 今後の確認

- 数日間、`/opt/receipt-ocr/.venv-py39-backup`を残す。
- timer実行後のjournalにPython 3.9 EOL警告が出ないことを継続確認する。
- I/O workerの周期（約5分）とLLM workerの周期（約1分）が維持されることを確認する。
- 問題が起きた場合はtimerを停止し、`.venv`を`.venv-py311-failed`へ退避して、`.venv-py39-backup`を`.venv`へ戻す。

## 関連資料

- [OCI PoCワーカーの認証設定と稼働開始](../OCI_POC_WORKER_ACTIVATION.md)
- [Codex CLI全自動レシート解析 実装・運用引き継ぎ書](2026-07-12_02_codex_cli_receipt_parser_implementation_handover.md)
