# Web確認画面の実運用改善案 引き継ぎ

作成日: 2026-07-20

対象: Firebase Hosting のWebアプリ（`web-app`）

## 実運用の受け入れ確認で分かったこと

確認待ち画面で、同一レシート画像を別々のDriveファイルとして二重に取り込んだレシートが2件表示された。
Drive file IDをレシートIDとしているため、同じ画像でも別ファイルとしてアップロードされると、現在の冪等化では重複を防げない。

Web画面には明細行を削除する操作はあるが、確認待ちレシート全体を取り消す操作はない。このため、誤取り込み・重複取り込みをWeb画面だけで解消できない。

## 改善案: 確認待ちレシートの削除

`確認`画面のレシート編集欄に **「このレシートを削除」** を追加する。

- 対象は `needs_review` のレシートだけに限定する。
- 店名、日付、合計金額を表示した確認ダイアログを必須にする。
- 削除時は、同じ `receiptId` を持つ `transactions` をすべて削除してから、`receipts/{receiptId}` を削除する。
- 対象の未解決 `system_alerts` は削除せず、`resolvedAt` を設定して解決済みにする。
- 実行中の確認対象が消えた後は、選択状態を解除して確認待ち一覧を再読込する。
- `confirmed` レシートの削除は今回の対象外とする。確定済みデータを取り消す操作は月次集計への影響が大きいため、別途「取消」仕様として設計する。

### 親子データを必ず同時に削除する

Firestoreは親文書を削除しても、別コレクションの関連文書を自動削除しない。
`receipts/{receiptId}` だけをFirestore Consoleで削除すると、`transactions` にある同じ `receiptId` のOCR明細が残り、取引一覧・月次集計へ表示され続ける。この状態を孤立明細と呼ぶ。

削除機能は、次のすべてを **1つの `writeBatch` でコミット** しなければならない。

1. `transactions` から `receiptId == 対象receiptId` の明細をすべて削除する。
2. `receipts/{receiptId}` を削除する。
3. `system_alerts` のうち `driveFileId == 対象receiptId` かつ未解決のものを `resolvedAt` 設定で解決する。

バッチが失敗した場合は削除済みとして画面を更新せず、エラーを表示する。部分削除を行わないことで、レシートだけ消えて明細が残る状態を防ぐ。

Firestoreの既存ルールでは、家計簿メンバーは `receipts` と `transactions` を削除でき、`system_alerts` は `resolvedAt` だけ更新できるため、ルール変更は不要である。

### 実装候補

- `web-app/src/data.ts` に、上記を1つの `writeBatch` で行う `removeReviewReceipt(receiptId)` を追加する。
- `web-app/src/App.tsx` の `ReceiptEditor` に危険操作用ボタンと確認ダイアログを追加する。
- 正常削除、確認キャンセル、削除失敗、対象alert解決をテストする。
- 受け入れ確認では、削除後に対象月の `取引`、`ホーム`のカテゴリ別支出、`確認`一覧を再読込し、対象レシートと全明細がいずれにも残らないことを確認する。
- テストでは、同じ `receiptId` を持つ複数明細を用意し、レシート削除後に明細が0件となることを必須確認にする。

### 既に親だけを削除してしまった場合の復旧

`取引`画面の左側にある「−」は支出を表すアイコンであり、削除ボタンではない。また、OCR由来の取引には取引画面からの削除操作はない。

Firestore Consoleで、残った各 `transactions` 文書の `receiptId` を確認し、削除済みレシートのIDを持つ文書だけを削除する。確認済みの正しいレシートの明細は削除しない。削除後、Web画面を再読込して「確認待ち」表示が残らないことを確認する。

## 値引き・税・手数料のカテゴリ扱い

税・値引き・手数料・端数を `調整` にすると、大カテゴリ別の集計が実際の支払額とずれる。そのため、全ての支出大カテゴリに **`値引き・税・手数料`** 小カテゴリを持たせる。

OCR/LLMは、レシート内の通常商品明細を大カテゴリごとに合計し、最も金額が大きい大カテゴリを求める。値引き・税・手数料・端数は、その大カテゴリの `値引き・税・手数料` へ登録する。

```text
かけ(大)             630円  食費 / 外食
かしわ天              220円  食費 / 外食
鮭おむすび            170円  食費 / 外食
5枚天ぷら100円引     -100円  食費 / 値引き・税・手数料
合計                  920円
```

これにより、食費の大カテゴリ集計も正しく920円になる。通常商品がなく大カテゴリを判定できない例外だけ、`調整` をフォールバックとして利用する。

### 実装と適用

- VMの `FirestoreWriter.list_allowed_categories()` が、既存の支出カテゴリ（Webで追加したカテゴリを含む）へこの小カテゴリを自動追加する。
- Webのカテゴリ追加・編集でも、支出カテゴリにはこの小カテゴリを自動で維持する。
- LLMへの指示と結果検証で、商品明細の金額が最大の大カテゴリ以外へ税・値引き・手数料を分類した結果を拒否する。
- 既存の確定済み取引は変更しない。反映後にOCRする新規レシートから適用される。

## 改善案: Androidアプリの保存先表示を実際の選択先へ合わせる

### 受け入れ確認で分かったこと

専用Androidアプリ「レシート撮影」でGoogle Pickerから `receipt-inbox-poc` を選択した。実際のアップロード先は正しく `receipt-inbox-poc` になったが、設定画面の表示は `保存先: receipt-inbox` のままだった。

これは表示上の問題ではあるが、利用者には通常運用用フォルダへ送信しているように見える。入力先を誤認してテストを重複実行したり、本番・PoCのデータを混在させたりするリスクがあるため、実運用前に修正する。

### 原因

`android-app/src/main/java/jp/hirata/receiptcapture/MainActivity.kt` のPicker完了処理は、選択したフォルダIDを `settings.folderId` へ保存している。一方、表示用の `settings.folderName` には選択結果に関係なく固定で `"receipt-inbox"` を保存している。

```kotlin
settings.folderId = folderId
settings.folderName = "receipt-inbox"
```

このため、アップロードは正しいフォルダIDへ行われるが、設定画面と完了Toastは常に `receipt-inbox` と表示される。

### 修正要件

- Pickerで選んだフォルダの実名を取得し、`folderId` と対で保存する。
- 設定画面の `保存先:` と完了Toastには、保存済みの実フォルダ名を表示する。
- アプリ再起動後も同じフォルダ名を表示する。
- フォルダ名を取得できない場合は、誤って `receipt-inbox` と表示せず、`選択済み（フォルダ名を取得できません）` など実態を誤認させない表示にする。
- `receipt-inbox-poc` を選択した受け入れテストで、表示・実アップロード先・保存済みフォルダIDがすべて一致することを確認する。

実装時はPickerの選択結果で名前を得られるか確認する。IDだけが返る場合は、許可済みの `drive.file` スコープでDrive APIから対象フォルダのメタデータ（`id`, `name`）を取得して保存する。

## 2026-07-20 修正実施内容

### Web確認画面

- `web-app/src/data.ts` に `removeReviewReceipt(receiptId)` を追加した。
  - 削除前に対象 `receipts/{receiptId}` が存在し、`needs_review` であることを確認する。`confirmed` は削除しない。
  - 同じ `receiptId` を持つ `transactions` をすべて削除する。
  - `driveFileId == receiptId` の未解決 `system_alerts` には `resolvedAt` を設定する。alert文書は削除しない。
  - 上記とレシート本体の削除を1つの `writeBatch` でコミットする。コミット失敗時には画面側の一覧を更新しない。
- `web-app/src/App.tsx` の確認待ちレシート編集欄に **「このレシートを削除」** を追加した。
  - 操作前に、店名・日付・合計金額を表示して確認する。
  - キャンセル時はFirestoreへ書き込まない。
  - 成功時は選択中のレシートを解除し、確認待ち一覧を再読込する。
- `web-app/src/data.test.ts` を追加し、複数明細の削除、未解決alertの解決、バッチ失敗時のエラー伝播を自動テストする。

### Androidアプリ

- `MainActivity.kt` はPicker完了後、選択済みフォルダIDを `drive.file` 権限のDrive APIで照会する。
- 取得した実フォルダ名を `folderId` と対で保存し、設定画面と完了Toastで表示する。
- `DriveFolderResolver.kt` を追加して、フォルダの `id` と `name` を取得する処理を分離した。
- フォルダ名を取得できなかった場合は `選択済み（フォルダ名を取得できません）` と保存・表示する。旧バージョンが固定保存した `receipt-inbox` も、実名を再取得するまで同じ安全な表示になる。

## 修正の適用方法

### 1. Webアプリを公開する

Firebase CLIへ対象プロジェクトの権限を持つアカウントでログイン済みであることを確認し、リポジトリのルートで実行する。

```bash
cd /Users/k-hirata/Documents/receipt-ocr/web-app
npm test
npm run build

cd /Users/k-hirata/Documents/receipt-ocr
firebase deploy --only hosting
```

Firestoreルールとインデックスは今回変更していないため、`firebase deploy --only firestore` は不要。

### 2. Androidアプリを更新する

以下はAndroid Studioを使う手順である。初回だけAndroid StudioがGradleやAndroid SDKのダウンロードを求める場合があるため、ネットワーク接続した状態で行う。

#### 事前準備

1. Android端末で **設定** → **デバイス情報** を開く。
2. **ビルド番号** を7回連続でタップし、画面ロックのPINなどを入力して「デベロッパー向けオプション」を有効にする。すでに有効なら不要。
3. **設定** → **システム** → **開発者向けオプション** を開き、**USBデバッグ** をオンにする。機種により設定内の場所や名称は少し異なる。
4. USBケーブルでMacとAndroid端末を接続する。端末に「USBデバッグを許可しますか？」と表示されたら、MacのRSAキーを許可する。普段は充電専用ケーブルではなく、データ通信対応のケーブルを使う。

#### Android Studioで更新版を端末へ入れる

1. Android Studioを起動する。
2. 初期画面なら **Open**、既に別プロジェクトを開いているなら **File** → **Open** を押す。
3. `/Users/k-hirata/Documents/receipt-ocr` を選び、**Open** を押す。`android-app` 単体ではなく、リポジトリのルートを開く。
4. 画面下部に「Gradle Sync」や「Indexing」と表示される場合は完了まで待つ。エラーが表示された場合は、まず **File** → **Sync Project with Gradle Files** を試す。
5. 上部ツールバーの実行構成が `android-app` であることを確認する。表示されていない場合は、実行構成のプルダウンから `android-app` を選ぶ。
6. 実行構成の右隣に、接続した端末名が表示されることを確認する。
   - 表示されない場合は、USBデバッグの許可画面を確認し、ケーブルをつなぎ直す。
   - **Tools** → **Device Manager** を開くと、端末が認識されているか確認できる。
7. 緑色の再生ボタン **Run 'android-app'**（▶）を押す。
8. 初回は「このアプリをUSB経由でインストールしますか」などの確認が端末に出ることがあるので許可する。
9. ビルド完了後、端末で「レシート撮影」が自動起動すれば更新完了。既にインストール済みの同じアプリは上書きされ、撮影待ちデータや設定は通常保持される。

#### APKファイルを作って入れる場合

Android Studioから直接実機へ入れられない場合は、APKを作成して手動インストールしてもよい。

1. Android Studioのメニューで **Build** → **Build Bundle(s) / APK(s)** → **Build APK(s)** を押す。
2. 完了通知にある **locate** を押す。APKは `android-app/build/outputs/apk/debug/android-app-debug.apk` に生成される。
3. APKをGoogle Drive、AirDrop、USBファイル転送などで端末へ渡し、端末のファイルアプリから開く。
4. 「不明なアプリのインストール」を許可する確認が出たら、今回使うファイルアプリだけを許可してインストールする。インストール後は必要に応じて許可をオフへ戻す。
5. 同じパッケージ名の旧版がある場合は上書きインストールされる。署名が異なるため上書きできないと表示された場合だけ、旧版を削除してから入れ直す。この場合はアプリ内の設定・未送信データも消えるため、先に必要な送信を終える。

#### 更新後に必ず行う再設定

1. 端末で「レシート撮影」を開き、下部の **設定** を押す。
2. **Google Driveフォルダを選択** を押す。
3. 支払者名を確認し、Googleアカウントを選ぶ。
4. Pickerで実際に使うフォルダ（PoCでは `receipt-inbox-poc`）を選び、**挿入** または **選択** を押す。
5. 完了Toastと設定画面の `保存先:` が、選んだフォルダ名になっていることを確認する。

コマンドでAPKを作成する場合は、リポジトリのルートで次を実行する。

```bash
cd /Users/k-hirata/Documents/receipt-ocr
./gradlew :android-app:testDebugUnitTest :android-app:assembleDebug
```

生成物は `android-app/build/outputs/apk/debug/android-app-debug.apk`。Android Studioから実機へ実行するか、`adb install -r android-app/build/outputs/apk/debug/android-app-debug.apk` で上書きインストールする。

更新後はアプリの **設定** で再度 **Google Driveフォルダを選択** を行う。旧バージョンが保存した固定名を実名へ置き換えるためである。

## 動作確認手順

### Web: 確認待ちレシート削除

1. `needs_review` のレシートを1件用意する。同じ `receiptId` を持つOCR明細を2件以上含め、可能なら同じIDの未解決 `system_alerts` も用意する。
2. 公開済み家計簿へログインし、**確認** から対象レシートを開く。
3. **このレシートを削除** を押す。確認表示に店名・日付・合計金額が正しく出ることを確認する。
4. いったんキャンセルし、レシートと明細が残ることを確認する。
5. 再度削除を実行して承認する。確認待ち一覧から対象が消え、編集欄が「レシートを選択してください」へ戻ることを確認する。
6. **取引**、対象月の**ホーム**、**確認**を再読込し、対象レシートと全明細が残っていないことを確認する。
7. Firestore Consoleで、対象 `receiptId` の `transactions` が0件であること、対応する `system_alerts` は残存しつつ `resolvedAt` が設定されていることを確認する。
8. エラー確認を行う場合は、テスト環境で一時的に削除権限を外して削除を試す。エラー表示後も画面の対象レシートが消えず、親だけ・明細だけの部分削除がないことを確認する。本番のルールは変更しない。

### Android: 保存先表示

1. 更新版APKを起動し、**設定** → **Google Driveフォルダを選択** を開く。
2. `receipt-inbox-poc` を選択して完了する。
3. 完了Toastと設定画面の `保存先:` がともに `receipt-inbox-poc` と表示されることを確認する。
4. アプリを終了して再起動し、同じ名前が表示されることを確認する。
5. レシートを1枚撮影・アップロードし、Google Drive上のアップロード先が `receipt-inbox-poc` であることを確認する。
6. 名前の照会に失敗する状況では、`receipt-inbox` ではなく `選択済み（フォルダ名を取得できません）` と表示されることを確認する。

## 2026-07-20 複数レシートの一括処理改善

### 修正内容

複数レシートモードでまとめて撮影した画像が、5分ごとのOCRワーカーで1枚ずつしか進まない問題を修正した。

- `cloud-worker --once` は、完了済みのLLM結果を最大4件まとめてFirestoreへ反映する。
- 続けて、未処理のDrive画像を最大4件までCloud Vision OCR・LLM待ちへ投入する。
- LLMワーカーは従来どおり1分ごとに1件ずつ解析する。4枚なら最長で約4分の解析後、次のOCRワーカー実行時（最大約5分後）に4件まとめてWebへ反映される。
- 1回あたりの件数は `poc.max_images_per_run` または環境変数 `POC_MAX_IMAGES_PER_RUN` で変更できる。未設定時は `4`。
- Cloud Visionの上限は当月の `max_vision_units` で判定する。累計値は監査用に保持するが、翌月の処理を止めない。

### OCI VMへの適用

OCI VMへ今回のソース更新を反映した後、`/etc/receipt-ocr-poc/config.json` の `poc` に以下を追加する。4枚を超える連続撮影を頻繁に行わない限り、`4` のままでよい。

```json
"max_vision_units": 800,
"max_images_per_run": 4,
```

環境変数で管理している場合は `/etc/receipt-ocr-poc/config.env` に次を追加してもよい。環境変数がある場合はこちらが優先される。

```text
POC_MAX_IMAGES_PER_RUN=4
POC_MAX_VISION_UNITS=800
```

設定・ソース更新後に、OCI VMで次を実行してサービス定義を読み直し、次回タイマー実行から新しい上限を適用する。

```bash
sudo systemctl daemon-reload
sudo systemctl restart receipt-ocr-poc.timer
sudo systemctl start receipt-ocr-poc.service
```

### 動作確認

1. 複数レシートモードで4枚を撮影し、アップロードする。
2. Google Driveの選択フォルダに4ファイルがあることを確認する。
3. 最初の `receipt-ocr-poc.service` 実行後、ログ出力JSONの `processed` に4件の `llm_pending` があることを確認する。
4. `receipt-ocr-llm.service` が順に4件を完了した後、次の `receipt-ocr-poc.service` 実行で4件がFirestoreへ反映されることを確認する。
5. Webの **確認** と **ホーム** を再読込し、各レシートが `confirmed` または `needs_review` として表示されることを確認する。未分類など安全確認が必要なレシートだけが確認待ちになる。

## 2026-07-20 Cloud Vision月次上限

### 修正内容

- OCR上限の判定を、Firestoreの累計 `poc_ocr_usage/_total` から当月の `poc_ocr_usage/YYYY-MM` へ変更した。
- 累計値は利用状況の監査用として更新を続けるが、月替わり後の新規OCRを停止させない。
- 既定の月次上限を `800` ユニットに変更した。Cloud Visionの月間無料枠1,000ユニットに対して200ユニットの余裕を残す。
- `POC_MAX_VISION_UNITS` は1〜1,000の範囲だけを受け付ける。無料枠を超える値は設定できない。

### OCI VMへの適用

OCI VM上の `/etc/receipt-ocr-poc/config.env` を開き、次の値へ変更する。

```text
POC_MAX_VISION_UNITS=800
```

まず、Mac上の更新をGitHubのVMが追跡しているブランチ（通常は `main`）へコミット・pushする。VMはGitHubから `/opt/receipt-ocr` へcloneされているため、push前にVMで `git pull` をしても更新は取得できない。

次にMacからOCI VMへSSH接続し、VM上で以下を実行する。`receipt-ocr-poc.timer` を一度停止することで、ソース更新の途中に定期処理が走らないようにする。

```bash
sudo systemctl stop receipt-ocr-poc.timer
sudo systemctl stop receipt-ocr-poc.service
sudo -u receipt-ocr git -C /opt/receipt-ocr pull --ff-only
sudo -u receipt-ocr /opt/receipt-ocr/.venv/bin/python -m unittest discover -s /opt/receipt-ocr/tests
```

`Already up to date.` ではなく更新コミットが取得され、テストが成功したことを確認する。その後、`/etc/receipt-ocr-poc/config.env` の `POC_MAX_VISION_UNITS` を `800` に変更してから、ワーカーを再起動する。

```bash
sudo systemctl daemon-reload
sudo systemctl restart receipt-ocr-poc.timer
sudo systemctl start receipt-ocr-poc.service
```

既に当月20件を消費していても、更新後は当月800件まで処理できる。`limit_reached` で止まっていたDrive画像は次回実行から自動的に処理対象へ戻る。

## 2026-07-20 カテゴリ編集機能

### 背景

Webのカテゴリ管理にはカテゴリ追加だけがあり、既存の大カテゴリへ小カテゴリを追加・削除するには、同じ大カテゴリ名で再登録して小カテゴリ配列全体を上書きする必要があった。既存の小カテゴリを入力し忘れると、選択肢から失われるリスクがある。

### 修正内容

- カテゴリ一覧の各行に **編集** ボタンを追加する。
- 編集画面では、対象カテゴリの既存小カテゴリをカンマ区切りで表示し、そのまま追加・削除できる。
- 大カテゴリ名と収支種別は編集対象外とする。カテゴリIDを変えず、既存取引のカテゴリ参照を壊さないためである。
- 保存時はFirestoreの該当カテゴリ文書を更新し、画面を再読込する。

### 利用手順

1. Web家計簿の **カテゴリ** を開く。
2. 変更したいカテゴリの **編集** を押す。
3. 小カテゴリ欄で、必要な語をカンマ区切りで追加・削除する。
4. **保存** を押し、一覧に反映されたことを確認する。

この変更はFirestoreへ即時保存され、以後OCI VMがLLM解析するレシートのカテゴリ候補にも反映される。すでに解析済みのレシートは自動で再分類しない。

## 2026-07-20 長いレシートのアップロード失敗

### 原因と修正

長いレシートでは複数の撮影画像を1枚のJPEGへ合成してからDriveへ送信する。合成先 `files/uploads/<sessionId>.jpg` の親フォルダ `uploads` を作成していなかったため、初回合成時に `open failed: ENOENT` となり、送信に失敗していた。

`ImageFiles.stitchOrdered` の開始時に、合成先の親フォルダを作成するよう修正した。

### 既に未送信の長いレシートを送る手順

1. 修正版APKを端末へ上書きインストールする。既存アプリをアンインストールしないこと。
2. アプリの **未送信** を開く。
3. 残っている長いレシートは破棄せず、先頭の **再送** を押す。
4. Wi-Fi接続中なら、2枚の画像を合成してDriveへアップロードする。成功すると未送信一覧から消える。
5. 続く長いレシートも順に送信される。残った場合は各行のエラーを確認して **再送** を押す。
