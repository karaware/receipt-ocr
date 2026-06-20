# Android レシートアップロード運用メモ

## 結論

スマホ側は自動化を必須にする。

無料運用を優先するなら、MacroDroidは第一候補にしない。

実機でMacroDroidに「無料 残り7日間」と表示される場合、継続無料運用には使えない前提で考える。

無料寄りの第一候補は **保存先を指定できるカメラアプリ + FolderSync**。

```text
保存先を指定できるカメラアプリ
  レシート画像を最初から receipt-ocr 用フォルダへ保存する

FolderSync
  receipt-ocr 用フォルダを Google Drive の receipt-inbox へアップロードする
```

MacroDroid / Tasker は強力だが、継続利用に課金が必要な場合は無料運用の候補から外す。

参考:

- Tasker: https://tasker.joaoapps.com/
- Open Camera: https://opencamera.org.uk/

## Google Drive側の準備

Google Driveに以下のフォルダを作る。

```text
receipt-inbox
receipt-processed
```

共有運用にする場合:

- 夫婦どちらもアクセスできるGoogle Driveフォルダにする
- どちらか一方のGoogleアカウントに作って、もう一方へ共有する
- Android側では `receipt-inbox` に画像を入れるだけにする

## 推奨: 保存先指定カメラ + FolderSync

### 役割分担

MacroDroidが継続無料で使えない場合は、ファイル移動の自動化をMacroDroidに頼らない。

代わりに、撮影時点でレシート画像を専用フォルダに保存する。

```text
保存先を指定できるカメラアプリ
  スマホ内の専用フォルダへ直接保存する

FolderSync
  専用フォルダをGoogle Driveへアップロードする
```

この構成なら、Google Driveへの同期部分をFolderSyncに任せられ、MacroDroid/Taskerなしで運用できる。

### Android側フォルダ

以下のような専用フォルダを作る。

```text
Pictures/receipt-ocr/
```

カメラ写真の保存先は端末によって異なる。代表例:

```text
DCIM/Camera/
Pictures/Camera/
Pictures/
```

実機で、撮影後の画像がどこに保存されるか確認してから設定する。

## FolderSync設定

### 使うアプリ

- FolderSync

### 目的

Android上の `Pictures/receipt-ocr/` に入った画像を、Google Driveの `receipt-inbox/` へアップロードする。

### 設定方針

FolderSyncでフォルダペアを作る。

```text
Local folder: Pictures/receipt-ocr/
Remote folder: Google Drive/receipt-inbox/
Sync type: Upload only
```

推奨設定:

- Wi-Fi接続時のみ同期
- 充電中のみ同期、またはバッテリー残量が十分なときだけ同期
- 同期頻度は最初は15分〜1時間おき
- 同期後にローカルファイルを削除する設定は、最初はOFF
- 数日運用して問題なければ、同期後削除をONにするか検討する

### 注意

同期方向は必ず **Upload only** にする。

双方向同期にすると、Google Drive側の整理や削除がスマホ側へ戻ってくるため、運用が複雑になる。

### SyncFailedException が出る場合

以下のようなエラーだけでは原因が分からない。

```text
dk.tacit.foldersync.exceptions.SyncFailedException
```

FolderSyncの同期履歴またはログ画面で、このスタックトレースの直前に出ているメッセージを確認する。

よくある原因:

- Local folder の権限がない
- Local folder のパス指定が違う
- Androidの「写真と動画」権限が「過去24時間にアクセス」や一部写真のみになっている
- Google Driveアカウントの認証が切れている
- Remote folder が存在しない、または権限がない
- Sync type が双方向やDownloadになっている
- Androidの省電力設定でFolderSyncが止められている
- Wi-Fiのみ同期などの条件に引っかかっている

切り分け手順:

1. `Pictures/receipt-ocr/` にテスト用画像を1枚だけ置く
2. FolderSyncのLocal folderをフォルダ選択画面から選び直す
3. Google DriveアカウントをFolderSync内で再認証する
4. Google Drive側に `receipt-inbox` を手動で作る
5. Remote folderをフォルダ選択画面から選び直す
6. Sync typeを `Upload only` にする
7. 「同期後削除」などの削除系オプションをOFFにする
8. Wi-Fiのみ/充電中のみなどの制約を一時的にOFFにする
9. 手動同期を実行する

最初の成功確認では、ファイル数を1枚にして、削除系オプションを全部OFFにする。成功してから条件を増やす。

Androidの権限画面でFolderSyncの「写真と動画」が以下のようになっている場合は、全画像を読めないことがある。

```text
過去24時間にアクセス
一部の写真と動画のみ
```

この場合は、FolderSyncの権限を開き、可能なら以下に変更する。

```text
すべての写真と動画を許可
```

または、Android設定の「特別なアプリアクセス」から以下を許可する。

```text
すべてのファイルへのアクセス
FolderSync: 許可
```

それでもFolderSync内で `DCIM/receipt-ocr/` の中身が空に見える場合は、Local folderをパス入力ではなくAndroidのフォルダ選択画面から選び直す。フォルダ選択画面で `DCIM/receipt-ocr/` を開き、「このフォルダを使用」または同等のボタンで許可する。

権限を「常にすべて許可」にしても `ファイルにアクセスする権限がありません` が出る場合は、次を確認する。

1. 同期タイプを `双方向同期` から `アップロードのみ` に変更する
2. 左側フォルダーを編集し、`/sdcard/DCIM/receipt-ocr/` の手入力ではなくフォルダ選択画面から選び直す
3. フォルダ選択時にAndroid標準の画面が出たら、`DCIM/receipt-ocr` を開いて「このフォルダを使用」を押す
4. 右側のGoogle Driveフォルダーもフォルダ選択画面から選び直す
5. 削除系オプションをOFFにする
6. まず1枚だけで手動同期する

`双方向同期` は最初の設定では使わない。Google Drive側の削除や変更がスマホ側に戻るため、権限エラーや意図しない削除の原因になりやすい。

最初のFolderSync設定は以下に固定する。

```text
Sync type:
  Upload only

Left folder:
  Device storage / DCIM / receipt-ocr

Right folder:
  Google Drive / receipt-inbox

Delete source files:
  Off

Delete target files:
  Off
```

解析画面で以下のように表示される場合:

```text
0 ファイル
0 フォルダ
0 B 転送するデータ
```

これはGoogle Drive側の問題ではなく、FolderSyncが左側フォルダー内の画像を見えていない可能性が高い。

確認すること:

1. FolderSyncの左側フォルダー選択画面で `DCIM/receipt-ocr/` を開いたとき、画像ファイルが表示されるか確認する
2. 画像が表示されない場合、左側フォルダーをいったん `DCIM/` に変更して解析し、`receipt-ocr` フォルダー自体が見えるか確認する
3. FolderSyncの同期オプションで、ファイル種別フィルター、除外フィルター、最小/最大ファイルサイズ、日付条件が入っていないか確認する
4. Android設定で `すべてのファイルへのアクセス` がFolderSyncに許可できる場合は許可する
5. FolderSync内でGoogle Drive側ではなく、ローカル左側フォルダーだけを選び直してから再解析する

`DCIM/receipt-ocr/` を直接選ぶと見えないが `DCIM/` は見える場合は、FolderSyncのローカルフォルダーを一時的に `DCIM/` にして、同期対象を `receipt-ocr` に絞るフィルターを使うか、Open Cameraの保存先をFolderSyncが見える別フォルダーに変更する。

## カメラアプリ設定

### 使うアプリ

- Open Camera など、保存先フォルダを指定できるカメラアプリ

Open Cameraは無料・オープンソースのAndroidカメラアプリ。

### 方針

レシート撮影時は、画像の保存先を最初から `Pictures/receipt-ocr/` にする。

### 設定イメージ

```text
Camera app:
  Save location: Pictures/receipt-ocr/

FolderSync:
  Pictures/receipt-ocr/ -> Google Drive/receipt-inbox/
```

この方式では、妻には「レシート撮影用カメラアプリで撮る」とだけ説明すればよい。

## MacroDroid設定

MacroDroidが継続無料で使える場合だけ検討する。

実機で「無料 残り7日間」と表示される場合は、この方式は採用しない。

### レシート撮影用ショートカット

```text
Macro name:
  レシート撮影

Trigger:
  Shortcut Launched
  または
  User Input / Floating Button / Quick Settings Tile

Actions:
  1. Launch Camera
  2. Wait Before Next Action: 10〜30秒
  3. File Operation:
       Copy or Move newest image
       From: DCIM/Camera/
       To: Pictures/receipt-ocr/
  4. Optional: Show Toast / Notification
       "レシート画像をアップロード対象に入れました"

Constraints:
  None
```

#### 注意

MacroDroidで「直近に撮影した画像だけ」を正確に選ぶ設定名は端末やMacroDroidバージョンで変わる可能性がある。

もし「最新ファイルだけ移動」が難しい場合は、次の方式にする。

### 推奨マクロ2: 専用フォルダ監視

カメラアプリやファイルアプリで、レシート画像を `Pictures/receipt-ocr/` に保存または移動する。その後のアップロードはFolderSyncに任せる。

```text
Pictures/receipt-ocr/ に画像が追加される
  -> MacroDroidが通知
  -> FolderSyncがGoogle Driveへアップロード
```

#### 設定イメージ

MacroDroid:

```text
Macro name:
  レシート画像検知

Trigger:
  File/Folder Change
  Folder: Pictures/receipt-ocr/
  Event: File created

Actions:
  1. Show Notification:
       "レシート画像を検知しました"
  2. Optional: Launch FolderSync sync shortcut

Constraints:
  Wi-Fi connected
```

この方式は、MacroDroidが画像の移動まで担当しないので壊れにくい。

### 推奨マクロ3: 定期的にカメラフォルダから移動

完全自動寄りにする場合の候補。

```text
一定時間ごとに DCIM/Camera を確認
  -> 新しいレシート候補画像を Pictures/receipt-ocr へ移動
  -> FolderSyncがGoogle Driveへアップロード
```

ただし、通常の写真まで拾うリスクがある。

これを使う場合は、以下のどちらかを条件にする。

- レシート撮影前にMacroDroidの「レシート撮影モード」をONにする
- レシート撮影専用のカメラアプリ/保存先を使う

#### 設定イメージ

```text
Macro name:
  レシート画像移動

Trigger:
  Regular Interval: 15 minutes

Actions:
  1. File Operation:
       Move files
       From: DCIM/Camera/
       To: Pictures/receipt-ocr/
       Filter: jpg/jpeg/png
       Condition: modified within last 30 minutes
  2. Show Notification:
       "レシート候補をアップロード対象に移動しました"

Constraints:
  Wi-Fi connected
  Optional: Charging
  Optional: レシート撮影モード variable is true
```

この方式は便利だが、普通の写真を誤ってアップロードするリスクがある。妻に使ってもらう運用では、最初は「レシート撮影ショートカット」方式の方が安全。

## 無料運用の現実的な判断

### MacroDroid

実機で「無料 残り7日間」と表示される場合、継続無料運用には向かない。

無料運用を優先するなら、MacroDroidは候補から外す。

### Tasker

Tasker公式サイトでは、入手方法として7日トライアルとPlay Store版が案内されている。継続無料運用には向かない。

無料にこだわるなら、Taskerは第一候補にしない。

ただし、有料でもよいならTaskerは最も柔軟。

## Taskerでやる場合

Taskerを使う場合も、Google Driveへの直接アップロードは避け、FolderSyncと分担するのが現実的。

```text
Tasker
  レシート画像を Pictures/receipt-ocr/ へ集める

FolderSync
  Pictures/receipt-ocr/ を Google Drive/receipt-inbox/ へアップロード
```

### Taskerプロファイル案

```text
Profile:
  Event -> File Modified
  Path: DCIM/Camera/

Task:
  1. List Files
       Dir: DCIM/Camera/
       Match: *.jpg
  2. Sort newest first
  3. Copy File or Move File
       From: newest image
       To: Pictures/receipt-ocr/
  4. Notify
       "レシート画像をアップロード対象に移動しました"
```

または、ホーム画面にTaskerショートカットを作る。

```text
Task:
  1. Launch App: Camera
  2. Wait: 20 seconds
  3. Copy/Move newest image from camera folder to Pictures/receipt-ocr/
  4. Notify
```

### Tasker単体でGoogle Drive APIへアップロードする案

可能ではあるが、MVPでは非推奨。

必要になるもの:

- Google Cloudプロジェクト
- OAuth認証
- Drive APIのスコープ設定
- アクセストークン/リフレッシュトークン管理
- HTTP POSTでmultipart upload
- トークン期限切れ時の更新処理

これは無料ではできても、設定と保守が重い。Mac側でGoogle Drive for desktopを使う方針と相性が悪い。

## 方法A: Google Driveアプリで手動アップロード

自動化前の動作確認用。

### 使うアプリ

- Google Drive Androidアプリ
- Android標準カメラアプリ

### 手順

1. レシートをスマホのカメラで撮る
2. 写真アプリで画像を開く
3. 共有ボタンを押す
4. Google Driveを選ぶ
5. 保存先に `receipt-inbox` を選ぶ
6. アップロードする

### メリット

- 追加アプリが少ない
- 妻にも説明しやすい
- 失敗時の原因が分かりやすい
- Google Drive for desktopとの相性がよい

### デメリット

- 完全自動ではない
- 撮影後に共有操作が必要

### MVPでの評価

最初の実運用テストには十分。まずこの方法で数日使い、OCR精度や家計簿フローの問題を見つける。

## 代替: Google Driveアプリのスキャン機能

### 使うアプリ

- Google Drive Androidアプリ

### メリット

- 追加アプリが少ない
- Google Driveに直接保存できる
- レシートの傾き補正やスキャン補正が効く可能性がある

### デメリット

- 自動化しにくい
- PDF保存になる場合があり、現状の `receipt-ocr` は画像中心
- 妻に毎回操作してもらうには手間が残る

### MVPでの評価

自動化必須の運用では第一候補にしない。

## レシート撮影のコツ

OCR精度を上げるため、撮影時は以下を守る。

- レシート全体をまっすぐ入れる
- 影を避ける
- ピンぼけを避ける
- 文字が小さくなりすぎないようにする
- 長いレシートは上半分・下半分に分けて撮る
- くしゃくしゃのレシートは軽く伸ばしてから撮る

長いレシートを1枚に収めると文字が小さくなり、明細OCRの精度が落ちやすい。家計簿用途では、最低限「店名・日付・合計」が取れれば使えるが、明細まで取りたいなら分割撮影が有利。

## Mac側の取り込み

Google Drive for desktopで `receipt-inbox` がMacから見える状態にする。

`receipt-ocr/config/config.json`:

```json
"drive": {
  "enabled": true,
  "source_dir": "~/Google Drive/receipt-inbox",
  "after_import": "archive",
  "archive_dir": "~/Google Drive/receipt-processed"
}
```

実行:

```bash
PYTHONPATH=src python3 -m receipt_ocr run --payer me --sync-drive
```

妻分として登録する場合:

```bash
PYTHONPATH=src python3 -m receipt_ocr run --payer wife --sync-drive
```

## 最初のおすすめ運用

1. Google Driveに `receipt-inbox` と `receipt-processed` を作る
2. AndroidにMacroDroidとFolderSyncを入れる
3. MacroDroidが継続無料で使えない場合はアンインストールする
4. Open Cameraなど保存先を指定できるカメラアプリを入れる
5. Androidに `Pictures/receipt-ocr/` を作る
6. カメラアプリの保存先を `Pictures/receipt-ocr/` にする
7. FolderSyncで `Pictures/receipt-ocr/` から `receipt-inbox` へのUpload only同期を作る
8. MacはGoogle Drive for desktopをストリーミングで使う
9. `receipt-ocr run --sync-drive` で処理する
10. Web画面で `receipts` と `items` を確認する
11. 未分類レビューで分類辞書を育てる
