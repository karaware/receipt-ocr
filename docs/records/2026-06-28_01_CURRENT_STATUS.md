# receipt-ocr 現状確認（2026-06-28）

## 結論

Google Driveへの画像アップロードは、現在は **このリポジトリで作ったAndroid専用アプリ**
`レシート撮影`（パッケージ名 `jp.hirata.receiptcapture`）を使う構成になっている。

初期案として記録されている一般アプリ利用は、次の2段階だった。

1. Android標準カメラとGoogle Driveアプリを使う手動アップロード
2. Open Cameraで撮影し、FolderSyncでDriveへ自動アップロード

2026-06-15には2番目の構成で実機からDriveへのアップロード成功が確認されている。その後、
撮影、未送信管理、Google認証、Driveアップロードを1つにまとめた専用Androidアプリへ移行している。

ただし、Git履歴は2026-06-20の初回コミットから始まり、その時点ですでに専用アプリ一式が
追加されている。したがって、専用アプリを作り始めた日や移行を決定したコミットまでは、この
リポジトリの履歴だけでは特定できない。

## 現在の全体構成

```text
Android専用アプリ「レシート撮影」
  -> Google Drive APIで receipt-inbox へJPEGを直接アップロード
  -> Google Drive for desktopでMacから同期フォルダとして参照
  -> Python CLIが data/inbox へ取り込み
  -> macOS VisionでOCR、解析、分類
  -> SQLite / CSVへ保存
  -> 必要に応じてFirebaseへ同期
  -> React製の家計簿Webアプリで確認・修正
```

Mac側はGoogle Drive APIを直接呼ばない。現時点の実装は、Google Drive for desktopがMacに
見せるローカルフォルダを `src/receipt_ocr/drive_client.py` が読み取る方式である。

## 専用Androidアプリの実装内容

対象コードは `android-app/` にあり、Android 12以降を対象としている。

- ComposeとCameraXによるアプリ内撮影
- 通常の複数レシート撮影と、複数画像を縦に連結する長いレシート撮影
- 画像の向き補正、最大長辺3,000pxへの縮小、JPEG化
- Roomによる撮影セッションと未送信画像の管理
- WorkManagerによるWi-Fi接続時のバックグラウンド送信と再試行
- Google Pickerによるアップロード先フォルダの選択
- OAuthの `drive.file` スコープだけを使った限定的なDriveアクセス
- Drive APIの再開可能アップロード
- `receipt_upload_id` をDriveの `appProperties` に保存する重複アップロード防止
- 支払者名、UTC撮影時刻、UUIDを含むファイル名
- アップロード成功後の端末内画像削除、失敗時の未送信保持と再送

専用アプリはサービスアカウント、クライアントシークレット、APIキー、
`google-services.json` を使用しない。Google Cloud側にはDrive API、Picker API、Android用
OAuthクライアント、OAuth同意画面の設定が必要である。

## 一般アプリ利用からの変遷

| 日付 | 確認できた状態 |
| --- | --- |
| 2026-06-15 | Open Cameraが `DCIM/receipt-ocr` に保存し、FolderSyncがGoogle Driveの `家計簿/receipt-ocr` へ送る構成で実機アップロード成功。Google Driveアプリによる手動共有・スキャン案も旧資料に記載。 |
| 2026-06-20 18:27 | Gitの初回コミット。旧運用資料と同時に、専用Androidアプリ、Mac側OCR、Drive同期フォルダ取り込みが追加済み。 |
| 2026-06-20 21:35 | `Fix Drive Picker setup flow`。Pickerがアカウントメールを返さない場合への対応、設定途中のActivity再生成対策、エラー表示、セットアップ資料の拡充。 |
| 2026-06-21 | Firebase同期と家計簿Webアプリを追加。これが現在のHEAD。 |

つまり、Google Driveアプリを使う手動案やOpen Camera + FolderSyncは **旧案・移行元** であり、
現在の主経路ではない。ただし旧形式の画像も処理できるよう、Python CLIの `--payer` は
フォールバックとして残されている。

## Mac側と家計簿Webアプリの状態

Python側には以下が実装されている。

- Google Drive同期フォルダからの画像取り込みと、取り込み元の保持・削除・アーカイブ
- macOS Vision OCR
- レシート解析、カテゴリ分類、SQLite保存、CSV出力
- ローカルレビュー画面
- Android専用アプリのファイル名からの支払者復元
- Firebaseへの冪等な同期、レビュー要否の判定、分類ルールの取り込み

Web側にはGoogleログイン、世帯単位のアクセス制御、月次表示、取引・レシート・予算・カテゴリの
画面が実装されている。ただし、実際のFirebaseプロジェクト設定、デプロイ済み環境、家族端末での
動作状況は、リポジトリのソースコードだけからは確認できない。

## 今回の検証結果

確認時のGit状態は `main`、`origin/main` と一致し、未コミット差分なしだった。

- HEAD: `28637f23281f607a559effd6f0a9a1da1c29cb3e`
- 最終コミット: 2026-06-21 `Add Firebase household budgeting app`
- Python: `python -m unittest discover -s tests -v` で17件すべて成功
- Android: `:android-app:testDebugUnitTest` 成功
- Android: `:android-app:assembleDebug` 成功
- Web: Vitest 1件成功
- Web: TypeScript + Viteの本番ビルド成功

Python環境には `pytest` が入っていなかったため `pytest` では実行できなかったが、テスト群は
標準の `unittest` で全件実行できた。Webビルドには、生成JavaScriptが500kBを超えるという
Viteの警告が1件ある。

この検証で確認できたのはソース、単体テスト、ローカルビルドまでである。専用Androidアプリから
Drive、MacのOCR、Firebaseまでの最新コードによる実機エンドツーエンド試験が完了した証拠は、
リポジトリ内にはない。2026-06-15の実機成功記録は旧Open Camera + FolderSync構成についてのもの。

## ドキュメント上の注意点

`README.md` には専用Androidアプリを「実装済み」と説明する節がある一方、その直後に
Open Camera + FolderSyncを現方針・今後の作業として書いた古い記述が残っている。実装と
`docs/ANDROID_APP_SETUP.md` に照らすと、専用アプリが現在の方針である。

また、旧資料の `receipt-inbox` と `家計簿/receipt-ocr` には保存先名の違いがある。専用アプリの
最新セットアップ資料とコードは `receipt-inbox` を前提にしている。

## 関連資料

- [Apple Vision OCRとGoogle Cloud Vision API OCRの比較](2026-06-28_02_OCR_COMPARISON.md)
- [専用Androidアプリのセットアップ](../ANDROID_APP_SETUP.md)
- [旧Androidアップロード案](../ANDROID_UPLOAD.md)
- [2026-06-15の初期ハンドオフ](2026-06-15_01_INITIAL_HANDOFF.md)
- [2026-06-15の実機確認後ハンドオフ](2026-06-15_02_HANDOFF.md)
- [Google Drive for desktop運用](../GOOGLE_DRIVE_DESKTOP.md)
- [Firebaseの構成](../FIREBASE_GUIDE.md)
- [Firebaseのセットアップ](../FIREBASE_SETUP.md)
