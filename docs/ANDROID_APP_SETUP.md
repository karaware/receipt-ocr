# Android専用アプリのセットアップ

## Google Cloud

1. Google Cloudプロジェクトで Google Drive API と Google Picker API を有効にする。
2. OAuth同意画面に `https://www.googleapis.com/auth/drive.file` を登録する。
3. Android OAuthクライアントを作り、パッケージ名
   `jp.hirata.receiptcapture` と配布APKの署名証明書SHA-1を登録する。
4. OAuthアプリを本番状態にするか、使用する家族のGoogleアカウントをテストユーザーへ追加する。

## ビルド

Android Studioでルートディレクトリを開くか、Gradleでビルドする。

```bash
./gradlew :android-app:assembleDebug
```

正式配布ではAndroid Studioの **Generate Signed Bundle / APK** から署名済みAPKを作る。
署名鍵はリポジトリへ保存しない。

## 初回設定

1. APKをAndroid 12以降の端末へインストールする。
2. 支払者名を入力する。
3. Google認証画面で端末利用者のアカウントを選ぶ。
4. Google Pickerで、書き込み権限を共有済みの `receipt-inbox` フォルダを選ぶ。
5. カメラと通知の権限を許可する。通知は認証エラー時だけ使用する。

画像はアプリ専用領域だけに保存され、アップロード成功後に削除される。
未送信画像はアプリの「未送信」画面から再送または破棄できる。
