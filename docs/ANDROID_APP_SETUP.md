# Android専用アプリのセットアップ

この手順は、家族2人のAndroid端末から同じGoogle Driveフォルダへレシートを送るためのものです。

以下を順番に行います。

1. Google Driveに保存先を作る
2. Google Cloudで2つのAPIを有効にする
3. Google Auth Platformを設定する
4. Android用OAuthクライアントを作る
5. APKを端末へ入れて初期設定する
6. DriveからMacまでの一連の動作を確認する

## 3つのGoogleアカウントの使い分け

この家庭では、次の3アカウントを役割ごとに使い分けます。

| 用途 | 使用するアカウント |
| --- | --- |
| Google Cloudプロジェクトの作成・管理 | 私のアカウント |
| `receipt-inbox` / `receipt-processed` の所有 | 家族共用アカウント |
| 私のAndroid端末でのアプリ認証 | 私のアカウント |
| 妻のAndroid端末でのアプリ認証 | 妻のアカウント |
| MacのGoogle Drive for desktop | 家族共用アカウント |

重要な点:

- Androidアプリでは家族共用アカウントへログインしません。
- 各自の端末では、各自の個人アカウントでGoogle認証します。
- 2台とも、家族共用アカウントが所有する同じ `receipt-inbox` を選びます。
- Google Cloudプロジェクトの管理者と、Driveフォルダの所有者が別アカウントでも問題ありません。
- 誰が支払ったかはGoogleアカウントではなく、各端末のアプリに設定する支払者名で判別します。

家族共用アカウントを両方のAndroid端末の認証に使うと、認証切れの影響が両端末へ同時に及び、
端末ごとのアクセス管理もしにくくなるため、この構成では採用しません。

## 0. このアプリで使う固定値

Google Cloud Consoleで入力するときは、次の値を使います。

| 項目 | 値 |
| --- | --- |
| アプリ名 | `レシート撮影` |
| Androidパッケージ名 | `jp.hirata.receiptcapture` |
| OAuthスコープ | `https://www.googleapis.com/auth/drive.file` |
| このMacのデバッグ署名SHA-1 | `9B:93:5F:52:EB:5B:30:45:B5:48:CD:23:E5:55:76:D8:22:E8:1E:D1` |
| Driveアップロード先 | `receipt-inbox` |

このアプリでは、サービスアカウント、クライアントシークレット、APIキー、
`google-services.json` は使用しません。

> SHA-1はAPKを署名した鍵ごとに異なります。上記の値は、このMacで作るデバッグAPK専用です。
> 配布用APKを作るときは、後述の手順で配布用署名鍵のSHA-1を別途登録します。

## 1. Google Driveにフォルダを作る

家族共用アカウントをフォルダの所有者にします。

1. 家族共用アカウントで [Google Drive](https://drive.google.com/) を開く。
2. 左上の **新規** を押す。
3. **新しいフォルダ** を押す。
4. フォルダ名に `receipt-inbox` と入力し、**作成** を押す。
5. 同じ手順で `receipt-processed` も作る。
6. `receipt-inbox` を右クリックし、**共有** → **共有** を押す。
7. 私のアカウントと妻のアカウントのメールアドレスを入力する。
8. 2人とも権限を **編集者** にして、**送信** を押す。
9. `receipt-processed` も私と妻のアカウントへ **編集者** として共有する。

私と妻の各アカウントでは、共有されたフォルダを見つけやすくしておきます。

1. 個人アカウントでGoogle Driveを開く。
2. 左側の **共有アイテム** を開く。
3. `receipt-inbox` を右クリックする。
4. **整理** → **ショートカットを追加** を押す。
5. **マイドライブ** を選び、**追加** を押す。
6. 私のアカウントと妻のアカウントの両方で同じ操作を行う。

アプリでは必ず `receipt-inbox` を選びます。`receipt-processed` はMacが処理済み画像を移す先です。

## 2. Google Cloudで対象プロジェクトを選ぶ

この操作は私のアカウントで行います。妻や家族共用アカウントでGoogle Cloudへログインする必要はありません。

1. 私のアカウントで [Google Cloud Console](https://console.cloud.google.com/) を開く。
2. 画面上部のプロジェクト名を押す。
3. 作成済みのこのアプリ専用プロジェクトを選ぶ。
4. 以降の各画面で、上部に同じプロジェクト名が表示されていることを確認する。

別のプロジェクトを選んだまま設定すると、アプリの認証が失敗します。

## 3. Google Drive APIを有効にする

1. 左上の **ナビゲーション メニュー（☰）** を押す。
2. **APIとサービス** → **ライブラリ** を開く。
3. 検索欄に `Google Drive API` と入力する。
4. 検索結果の **Google Drive API** を押す。
5. **有効にする** を押す。
   - ボタンが **管理** になっていれば、すでに有効です。
6. 有効化後、ブラウザの戻る操作か **APIライブラリ** でライブラリへ戻る。

## 4. Google Picker APIを有効にする

Google Drive APIとは別のAPIなので、両方必要です。

1. **APIとサービス** → **ライブラリ** を開く。
2. 検索欄に `Google Picker API` と入力する。
3. 検索結果の **Google Picker API** を押す。
4. **有効にする** を押す。
   - ボタンが **管理** なら、すでに有効です。
5. **APIとサービス** → **有効なAPIとサービス** を開く。
6. 一覧に次の2つがあることを確認する。
   - Google Drive API
   - Google Picker API

## 5. Google Auth Platformの初期設定

Google Cloud Consoleの左上の **ナビゲーション メニュー（☰）** から
**Google Auth Platform** → **ブランディング** を開きます。

### 「Google Auth Platform はまだ構成されていません」と表示された場合

1. **使ってみる** または **開始** を押す。
2. **アプリ情報** で次を入力する。
   - アプリ名: `レシート撮影`
   - ユーザーサポートメール: 自分のGoogleアカウント
3. **次へ** を押す。
4. **対象** または **ユーザーの種類** で **外部** を選ぶ。
   - 個人のGmailアカウントで夫婦利用する場合は **外部** を選びます。
   - **内部** は同じGoogle Workspace組織内だけで使う場合の選択肢です。
5. **次へ** を押す。
6. **連絡先情報** に自分のメールアドレスを入力する。
7. **次へ** を押す。
8. **完了** でGoogle APIサービスのユーザーデータポリシーを確認する。
9. 同意のチェックを入れ、**続行** を押す。
10. **作成** を押す。

すでに初期設定済みなら、この操作は不要です。左側に
**ブランディング**、**対象**、**データアクセス**、**クライアント** が表示されます。

### ブランディングを確認する

**Google Auth Platform** → **ブランディング** を開き、最低限次を確認します。

- アプリ名: `レシート撮影`
- ユーザーサポートメール: 自分のメールアドレス
- デベロッパーの連絡先情報: 自分のメールアドレス

ロゴ、ホームページ、プライバシーポリシー、利用規約は、家族だけでテストする段階では空欄で構いません。

## 6. 利用するGoogleアカウントをテストユーザーへ追加する

1. **Google Auth Platform** → **対象** を開く。
2. 公開ステータスが **テスト** になっていることを確認する。
3. **テストユーザー** の欄までスクロールする。
4. **ユーザーを追加** を押す。
5. 私のアカウントと妻のアカウントのメールアドレスを入力する。
6. **保存** を押す。

ここに追加していないアカウントで試すと、認証画面でアクセス拒否になることがあります。
家族共用アカウントはAndroidアプリの認証には使わないため、テストユーザーへ追加する必要はありません。

まずは **テスト** のまま実機動作を確認します。動作確認後は、同じ **対象** 画面の
**アプリを公開** を使って **本番環境** に変更することを推奨します。テスト状態の外部向けOAuthアプリは、
認可が短期間で期限切れになることがあるためです。

このアプリが要求する `drive.file` は、ユーザーがPickerで選択したファイルやフォルダに限定されたスコープです。
Drive全体を操作する `https://www.googleapis.com/auth/drive` は追加しないでください。

## 7. `drive.file` スコープを登録する

1. **Google Auth Platform** → **データアクセス** を開く。
2. **スコープを追加または削除** を押す。
3. 表示された表の検索・フィルター欄に `drive.file` と入力する。
4. 次のスコープのチェックボックスをオンにする。

   ```text
   https://www.googleapis.com/auth/drive.file
   ```

5. 画面下部の **更新** を押す。
6. データアクセス画面に戻ったら **保存** を押す。
7. スコープ一覧に `.../auth/drive.file` が表示されることを確認する。

スコープが検索結果に出ない場合は、先にGoogle Drive APIが有効になっているか確認してください。

## 8. Android用OAuthクライアントを作る

ここでは、このリポジトリで生成済みのデバッグAPKを動かすためのクライアントを作ります。

1. **Google Auth Platform** → **クライアント** を開く。
2. **クライアントを作成** を押す。
3. **アプリケーションの種類** で **Android** を選ぶ。
4. 次を入力する。

   | 入力欄 | 入力値 |
   | --- | --- |
   | 名前 | `Receipt Capture Android Debug` |
   | パッケージ名 | `jp.hirata.receiptcapture` |
   | SHA-1 証明書フィンガープリント | `9B:93:5F:52:EB:5B:30:45:B5:48:CD:23:E5:55:76:D8:22:E8:1E:D1` |

5. **作成** を押す。
6. クライアント一覧に `Receipt Capture Android Debug` が表示されることを確認する。

作成後に表示されるクライアントIDを、ソースコードへ貼り付ける必要はありません。
Google Play開発者サービスが、パッケージ名と署名SHA-1を使って対象クライアントを照合します。

### SHA-1を自分で再確認する方法

このMacでは次のコマンドで確認できます。

```bash
keytool -list -v \
  -alias androiddebugkey \
  -keystore ~/.android/debug.keystore \
  -storepass android
```

出力の **証明書のフィンガプリント** → **SHA1** を確認します。

別のMacでデバッグAPKを作るとSHA-1が変わります。その場合は同じパッケージ名で、
そのMacのSHA-1を指定したAndroid OAuthクライアントをもう1件作成します。

## 9. デバッグAPKを準備する

リポジトリのルートで次を実行します。

```bash
./gradlew :android-app:assembleDebug
```

生成先:

```text
android-app/build/outputs/apk/debug/android-app-debug.apk
```

現在のリポジトリには、すでにビルド済みAPKがあります。

## 10. Android端末へインストールする

### USB接続でインストールする場合

USB接続では、Android SDKの `adb`（Android Debug Bridge）を使ってMacからAPKを送ります。
このMacには `adb` とビルド済みAPKがすでにあります。

#### 1. データ通信対応のUSBケーブルを用意する

充電専用ケーブルでは `adb` が端末を検出できません。普段データ転送にも使えるUSBケーブルで、
Android端末とMacを直接接続します。USBハブ経由で認識しない場合はMacへ直接つなぎます。

この時点では、まだMac側のコマンドを実行しなくて構いません。

#### 2. Androidの「開発者向けオプション」を表示する

端末ごとに次の操作を行います。

Google Pixelなど標準Androidに近い端末:

1. Androidの **設定** を開く。
2. **デバイス情報** または **デバイスについて** を開く。
3. 一番下付近の **ビルド番号** を7回連続で押す。
4. 端末のPIN、パターン、パスワードを求められたら入力する。
5. 「これでデベロッパーになりました」などと表示されることを確認する。

Samsung Galaxy:

1. Androidの **設定** を開く。
2. **端末情報** を開く。
3. **ソフトウェア情報** を開く。
4. **ビルド番号** を7回連続で押す。
5. 端末のPINなどを入力する。

すでに有効な場合は「デベロッパー モードはすでに有効です」と表示されます。

#### 3. USBデバッグを有効にする

Google Pixelなど:

1. **設定** → **システム** を開く。
2. **開発者向けオプション** を開く。
   - 見つからない場合は設定画面上部で「開発者向けオプション」を検索する。
3. 画面上部の開発者向けオプション自体がオンになっていることを確認する。
4. **デバッグ** セクションの **USBデバッグ** をオンにする。
5. 確認画面で **OK** を押す。

Samsung Galaxy:

1. **設定** の最初の画面へ戻る。
2. 一番下付近の **開発者向けオプション** を開く。
3. **USBデバッグ** をオンにする。
4. 確認画面で **OK** を押す。

「USB経由でアプリをインストール」などの別項目がある端末では、それもオンにする必要がある場合があります。

#### 4. USBの用途を確認する

1. Android端末の画面ロックを解除した状態でMacへ接続する。
2. Androidの通知欄を開く。
3. 「USBでこのデバイスを充電中」などの通知を押す。
4. USBの用途で **ファイル転送 / Android Auto** を選ぶ。

端末によっては「充電のみ」のままでも `adb` が動きますが、検出されない場合はファイル転送へ変更します。

#### 5. Macのターミナルでリポジトリへ移動する

Codex内蔵ターミナル、またはmacOSのターミナルを開き、次を実行します。

```bash
cd /Users/k-hirata/Documents/receipt-ocr
```

以降のコマンドを短くするため、`adb` の場所を変数へ入れます。

```bash
ADB="$HOME/Library/Android/sdk/platform-tools/adb"
```

`adb` が使用できることを確認します。

```bash
"$ADB" version
```

次のように `Android Debug Bridge version` が表示されれば準備完了です。

#### 6. Macから端末を検出する

Android端末を接続し、画面ロックを解除した状態で次を実行します。

```bash
"$ADB" devices -l
```

初回接続時は、Android端末に **USBデバッグを許可しますか？** という確認が出ます。

1. RSAキーフィンガープリントの確認画面で **このパソコンからのUSBデバッグを常に許可する** にチェックする。
2. **許可** を押す。
3. Macでもう一度 `devices -l` を実行する。

成功例:

```text
List of devices attached
XXXXXXXXXXXX    device product:... model:... device:...
```

端末の行に `device` と表示されれば接続成功です。

次の表示では、まだインストールへ進みません。

- `unauthorized`: Android側のUSBデバッグ許可が終わっていない
- `offline`: 接続は見えているが応答していない
- 端末の行がない: ケーブル、USB用途、USBデバッグのいずれかに問題がある

#### 7. APKが存在することを確認する

```bash
ls -lh android-app/build/outputs/apk/debug/android-app-debug.apk
```

ファイルがなければ、次を実行して作ります。

```bash
./gradlew :android-app:assembleDebug
```

#### 8. APKをインストールする

接続端末が1台だけなら、次を実行します。

```bash
"$ADB" install -r \
  android-app/build/outputs/apk/debug/android-app-debug.apk
```

`-r` は、すでにアプリが入っている場合にアプリ内データを残したまま更新する指定です。

成功すると最後に次のように表示されます。

```text
Performing Streamed Install
Success
```

端末が複数接続されている場合やAndroidエミュレータが起動している場合は、実機を指定します。

```bash
"$ADB" -d install -r \
  android-app/build/outputs/apk/debug/android-app-debug.apk
```

#### 9. インストール結果を確認する

Macで次を実行します。

```bash
"$ADB" shell pm path jp.hirata.receiptcapture
```

`package:/data/app/.../base.apk` のようなパスが表示されればインストール済みです。

Androidのアプリ一覧から **レシート撮影** を探して起動します。その後は
「11. アプリの初回設定」へ進みます。

#### USB接続でよくあるエラー

`unauthorized` と表示される:

1. Androidの画面ロックを解除する。
2. USBデバッグ許可画面を確認する。
3. 許可画面が出ない場合は、開発者向けオプションの **USBデバッグの許可を取り消す** を押す。
4. USBケーブルを抜き差しし、再び `"$ADB" devices -l` を実行する。

端末が何も表示されない:

1. 充電専用ではない別のUSBケーブルを試す。
2. USBハブを外してMacへ直接接続する。
3. AndroidのUSB用途を **ファイル転送 / Android Auto** にする。
4. USBデバッグを一度オフにしてからオンにする。
5. Mac側のADBを再起動する。

```bash
"$ADB" kill-server
"$ADB" start-server
"$ADB" devices -l
```

`adb: more than one device/emulator`:

- インストールコマンドを `"$ADB" -d install -r ...` に変更して実機を指定する。
- またはAndroid Studioのエミュレータを終了する。

`INSTALL_FAILED_UPDATE_INCOMPATIBLE`:

以前インストールしたアプリと今回のAPKで署名鍵が異なります。未送信画像がないことを確認してから、
古いアプリを削除して再インストールします。次のコマンドはアプリ内データも削除します。

```bash
"$ADB" uninstall jp.hirata.receiptcapture
"$ADB" install android-app/build/outputs/apk/debug/android-app-debug.apk
```

`INSTALL_FAILED_VERSION_DOWNGRADE`:

端末に入っているアプリの方が新しい場合に発生します。通常は新しいAPKを作り直すか、
未送信画像がないことを確認して一度アンインストールしてから入れ直します。

### APKファイルを端末へ送る場合

1. `android-app-debug.apk` を端末へ送る。
2. AndroidのファイルアプリからAPKを開く。
3. 「この提供元からのアプリを許可」が表示されたら、今回APKを開いたアプリに対して許可する。
4. **インストール** を押す。

デバッグAPKはGoogle Play外から入れるため、Play Protectの確認が表示される場合があります。

## 11. アプリの初回設定

Wi-Fiへ接続した状態で行います。

1. Androidで **レシート撮影** アプリを起動する。
2. 通知権限を求められたら **許可** を押す。
   - 通知は、認証切れなどアップロードを継続できない場合だけ使用します。
3. 支払者名を入力する。
   - 自分の端末の例: `me`
   - 妻の端末の例: `wife`
   - 日本語名でも動作しますが、CSV上で統一したい値を使ってください。
4. **Google Driveフォルダを選択** を押す。
5. Googleアカウント選択画面で、その端末の利用者本人のアカウントを選ぶ。
   - 私の端末: 私のアカウント
   - 妻の端末: 妻のアカウント
   - 家族共用アカウントは選ばない
6. アクセス確認画面が出たら内容を確認し、**続行** または **許可** を押す。
7. Google Pickerが開いたら `receipt-inbox` フォルダを開く。
8. フォルダを選択した状態で **挿入**、**選択**、または **このフォルダを使用** を押す。
   - Samsung端末のGoogle Pickerでは、スクリーンショットのように **挿入** と表示されます。
   - フォルダの中へ移動するのではなく、フォルダ行が青く選択された状態で **挿入** を押します。
9. カメラ権限を求められたら **アプリの使用時のみ** を押す。
10. カメラ画面が表示されることを確認する。

個人アカウントでフォルダが見つからない場合は、Picker内の **共有アイテム** を確認します。
事前にマイドライブへショートカットを追加しておくと見つけやすくなります。

## 12. 最初のアップロードテスト

最初は通常の「1画像＝1レシート」で試します。

1. カメラ上部で **複数レシート** を選ぶ。
2. レシートを1枚撮影する。
3. 撮影画像が表示され、枚数が `1枚` になっていることを確認する。
4. **アップロード** を押す。
5. Wi-Fi接続中であることを確認する。
6. Google Driveの `receipt-inbox` をブラウザで開く。
7. 次の形式のJPEGが追加されることを確認する。

   ```text
   receipt__<支払者名のエンコード値>__<撮影日時>__<UUID>.jpg
   ```

8. アプリの **未送信** が0件になることを確認する。

次に、Wi-Fi再送を確認します。

1. AndroidのWi-Fiをオフにする。
2. レシートを撮影して **アップロード** を押す。
3. **未送信** に1件残ることを確認する。
4. Wi-Fiをオンにする。
5. しばらく待ち、Driveへ追加されて未送信が0件になることを確認する。

## 13. Mac側まで通して確認する

MacのGoogle Drive for desktopには家族共用アカウントでログインします。
家族共用アカウントのマイドライブにある `receipt-inbox` がMacから見えるようにした上で、
`config/config.json` の `drive` を設定します。

```json
"drive": {
  "enabled": true,
  "source_dir": "~/Google Drive/receipt-inbox",
  "after_import": "archive",
  "archive_dir": "~/Google Drive/receipt-processed"
}
```

実際のFinder上のパスが異なる場合は、そのパスへ変更してください。

取り込みとOCRを実行します。

```bash
PYTHONPATH=src python3 -m receipt_ocr run --sync-drive
```

確認項目:

- `imported=1` と表示される
- `processed=1` と表示される
- `data/export/receipts.csv` にレシートが追加される
- `payer` にAndroidで設定した支払者名が入る
- Drive上の元画像が `receipt-processed` へ移動する

## 14. 配布用の署名済みAPKを作るとき

デバッグAPKで実機テストが完了してから行います。

1. Android Studioでこのリポジトリを開く。
2. メニューの **Build** → **Generate Signed Bundle / APK** を押す。
3. **APK** を選び、**Next** を押す。
4. **Create new...** を押す。
5. Key store path、パスワード、Alias、有効期限、証明書情報を入力して署名鍵を作る。
6. 署名鍵ファイルはリポジトリ外の安全な場所に保存する。
7. **release** を選んで署名済みAPKを生成する。

配布用署名鍵のSHA-1を確認します。

```bash
keytool -list -v -alias <作成したAlias> -keystore <署名鍵へのパス>
```

Google Cloud Consoleで次を追加します。

1. **Google Auth Platform** → **クライアント** を開く。
2. **クライアントを作成** → **Android** を選ぶ。
3. 名前を `Receipt Capture Android Release` にする。
4. パッケージ名に `jp.hirata.receiptcapture` を入力する。
5. 配布用署名鍵のSHA-1を入力する。
6. **作成** を押す。

デバッグ用クライアントは消さず、デバッグ用と配布用の2件を残して構いません。

## 15. よくあるエラー

### Googleログイン直後にエラーになる／Developer error 10

次を確認します。

- Google Cloud Consoleで正しいプロジェクトを選んでいるか
- OAuthクライアントの種類が **Android** か
- パッケージ名が `jp.hirata.receiptcapture` と完全一致しているか
- SHA-1が、インストールしたAPKを署名した鍵のSHA-1と一致しているか
- 別のMacで作ったAPKを使っていないか

### 「アクセスをブロックしました」「このアプリにアクセスできません」

- **Google Auth Platform** → **対象** のテストユーザーに、そのGoogleアカウントを追加する
- OAuth同意画面のユーザーの種類が **外部** になっているか確認する
- Androidで選択したGoogleアカウントが、登録したテストユーザーと一致するか確認する

### `drive.file` がスコープ一覧に出ない

- Google Drive APIが有効か確認する
- **データアクセス** → **スコープを追加または削除** の検索欄へ
  `https://www.googleapis.com/auth/drive.file` を完全な形で貼り付ける

### Pickerに `receipt-inbox` が見つからない

- そのGoogleアカウントが `receipt-inbox` の **編集者** か確認する
- Google Driveの **共有アイテム** を確認する
- 共有フォルダのショートカットをマイドライブへ追加する
- Androidで別のGoogleアカウントを選んでいないか確認する

### Driveへのアップロードが403または404になる

- Google Drive APIとGoogle Picker APIの両方が有効か確認する
- 選択したフォルダが削除・移動されていないか確認する
- 利用者がフォルダの **閲覧者** ではなく **編集者** になっているか確認する
- アプリの **設定** からGoogleアカウント・保存先を選び直す

### しばらくすると再認証を求められる

実機テストが済んでいる場合は、**Google Auth Platform** → **対象** で
**アプリを公開** を押し、公開ステータスを **本番環境** に変更します。

### 設定を最初からやり直したい

1. Androidの **設定** → **アプリ** → **レシート撮影** を開く。
2. **ストレージとキャッシュ** → **ストレージを消去** を押す。
3. アプリを起動して支払者名とDriveフォルダを設定し直す。

未送信画像も削除されるため、ストレージを消去する前に未送信が0件か確認してください。

## 参考資料

- [OAuth同意画面とスコープの設定](https://developers.google.com/workspace/guides/configure-oauth-consent?hl=ja)
- [Android OAuthクライアントの作成](https://developers.google.com/workspace/guides/create-credentials)
- [Android・モバイル向けGoogle Picker](https://developers.google.com/workspace/drive/picker/guides/desktop-mobile-picker)
- [Google Drive APIの有効化](https://developers.google.com/workspace/drive/api/guides/enable-sdk)
