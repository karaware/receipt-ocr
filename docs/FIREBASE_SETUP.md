# Firebase家計簿 完全セットアップ手順

この手順は、Firebase Consoleを一度も開いたことがない人を対象にしています。
画面上で選ぶ項目、コマンドを実行する場所、成功時の確認方法まで順番に説明します。

Firebaseの仕組みを先に知りたい場合は
[`FIREBASE_GUIDE.md`](./FIREBASE_GUIDE.md)を読んでください。

## この作業で完成するもの

すべて完了すると、次の状態になります。

- 本人と妻が外出先から家計簿Webアプリを開ける
- 各自のGoogleアカウントでログインできる
- 許可した2アカウント以外は家計データを閲覧できない
- MacBookでOCRしたデータをFirestoreへ送信できる
- MacBookが停止していても、同期済みデータは閲覧・編集できる
- FirebaseはSpark無料プランのまま使用する

## 全体の作業順序

```text
1. 使用するGoogle Cloudプロジェクトを確認
2. そのプロジェクトへFirebaseを追加
3. FirebaseへWebアプリを登録
4. Googleログインを有効化
5. Firestoreデータベースを作成
6. Mac用の秘密鍵を取得
7. Macの設定ファイルを編集
8. 本人・妻を許可リストへ登録
9. Security Rulesを公開
10. Webアプリを公開
11. 既存レシートを移行
12. 本人・妻のスマホで動作確認
```

## 作業前に用意するもの

- このMacBook
- 本人のGoogleアカウント
- 妻がログインに使うGoogleアカウントのメールアドレス
- インターネット接続
- ターミナル
- Google ChromeまたはSafari

作業は、Google Cloudの既存Androidアプリ設定を行った本人のGoogleアカウントで進めます。
妻のGoogleアカウントでFirebase Consoleを操作する必要はありません。

## 画面と用語

この手順では2つの管理画面を使います。

| 管理画面 | URL | 用途 |
|---|---|---|
| Firebase Console | <https://console.firebase.google.com/> | 認証、Firestore、Hosting、Webアプリ |
| Google Cloud Console | <https://console.cloud.google.com/> | 既存プロジェクトと請求状態の確認 |

Firebase Consoleを開くと、プロジェクト選択後の画面はおおむね次の構造です。

```text
┌─────────────────────────────────────────────┐
│ Firebase                         アカウント │
├───────────────┬─────────────────────────────┤
│ プロジェクト概要│                             │
│               │       選択した機能の画面       │
│ Build         │                             │
│  Authentication│                            │
│  Firestore    │                             │
│  Hosting      │                             │
│               │                             │
│ ⚙ 設定        │                             │
└───────────────┴─────────────────────────────┘
```

日本語表示と英語表示では、次のように名称が異なります。

| 日本語 | 英語 |
|---|---|
| プロジェクトの概要 | Project Overview |
| プロジェクトの設定 | Project settings |
| 構築 | Build |
| 認証 | Authentication |
| Firestore Database | Firestore Database |
| ホスティング | Hosting |
| 使用量と請求 | Usage and billing |

画面名称が多少変わっていても、英語名やアイコンを目印にしてください。

---

# 第1部: 使用するプロジェクトを決める

## 1. 既存Google Cloudプロジェクトを確認する

Android撮影アプリのGoogle Drive連携で使ったGoogle Cloudプロジェクトがすでにあります。
そのプロジェクトが `receipt-ocr` 専用で、請求が有効になっていなければ再利用します。

1. [Google Cloud Console](https://console.cloud.google.com/)を開く。
2. 本人のGoogleアカウントでログインする。
3. 画面上部のプロジェクト名を押す。
4. Android撮影アプリの設定で使用したプロジェクトを選ぶ。
5. 画面上部に選んだプロジェクト名が表示されていることを確認する。
6. **プロジェクトID** をメモする。

プロジェクト名とプロジェクトIDは別物です。

```text
プロジェクト名: receipt-oci
プロジェクトID: YOUR_PROJECT_ID
```

この後は、各画面の上部に同じプロジェクト名が表示されていることを毎回確認してください。

## 2. 請求先アカウントがないことを確認する

無料運用で最も重要な確認です。

1. Google Cloud Console左上の **ナビゲーション メニュー（☰）** を押す。
2. **お支払い** または **Billing** を開く。
3. 選択中のプロジェクトの請求状態を確認する。

### 「このプロジェクトには請求先アカウントがありません」等と表示される

既存プロジェクトを再利用して構いません。

### 請求先アカウント名や請求概要が表示される

そのプロジェクトへFirebaseを追加すると、FirebaseはBlaze従量課金プランになります。
無料厳守のため、この場合は既存プロジェクトを使わず、第2部で新しいFirebaseプロジェクトを
作ってください。

Firebase公式にも、請求が有効なGoogle CloudプロジェクトへFirebaseを追加するとBlazeに
なると記載されています。

- [既存Google CloudプロジェクトへFirebaseを追加する際の注意](https://firebase.google.com/docs/projects/use-firebase-with-existing-cloud-project)

## 3. 判断結果を記録する

次のどちらかを選びます。

```text
[-] A. 既存のreceipt-ocr用Google Cloudプロジェクトを再利用する
[ ] B. Firebase家計簿用の新規プロジェクトを作る
```

推奨:

- 既存プロジェクトがreceipt-ocr専用かつ請求なし: A
- 既存プロジェクトが他用途と共用、または請求あり: B

---

# 第2部: Firebaseプロジェクトを準備する

## 4-A. 既存Google CloudプロジェクトへFirebaseを追加する

第1部でAを選んだ場合の手順です。

1. [Firebase Console](https://console.firebase.google.com/)を開く。
2. Google Cloud Consoleと同じ本人アカウントでログインする。
3. 初回に利用規約への同意画面が出たら、内容を確認して同意する。
4. **プロジェクトを作成** または **Add project** を押す。
5. プロジェクト作成画面の下部にある
   **Google CloudプロジェクトにFirebaseを追加** を押す。
6. 入力欄に既存プロジェクトの名前またはプロジェクトIDを入力する。
7. 候補から第1部で確認したプロジェクトを選ぶ。
8. **プロジェクトを開く** を押す。
9. Firebase利用規約が表示されたら確認して続行する。
10. Gemini in Firebaseは **有効にしなくてよい**。
11. Google Analyticsは **今回は有効にしない**。
12. **Firebaseを追加** を押す。
13. 完了するまで待ち、**続行** を押す。

公式手順:

- [既存Google CloudプロジェクトでFirebaseを開始](https://firebase.google.com/docs/projects/use-firebase-with-existing-cloud-project?hl=ja)

注意:

- Firebase追加後に「Firebaseだけを完全に取り外す」ことはできません。
- プロジェクトを削除すると、既存のDrive API・OAuth設定も含めて削除されます。
- この手順ではプロジェクトを削除しないでください。

## 4-B. 新しいFirebaseプロジェクトを作る

第1部でBを選んだ場合だけ実行します。

1. [Firebase Console](https://console.firebase.google.com/)を開く。
2. **プロジェクトを作成** を押す。
3. プロジェクト名に `receipt-ocr-household` など分かりやすい名前を入力する。
4. プロジェクトIDの編集アイコンが表示されたら、内容を確認する。
   - プロジェクトIDは公開URLの一部になる。
   - 後から変更できない。
   - 自動生成された値のままでもよい。
5. **続行** を押す。
6. Gemini in Firebaseは **有効にしなくてよい**。
7. Google Analyticsは **今回は有効にしない**。
8. **プロジェクトを作成** を押す。
9. 完了したら **続行** を押す。

新規プロジェクトは通常Spark無料プランで作成されます。支払い情報を入力する必要はありません。

## 5. Sparkプランを確認する

Firebase Consoleで作成・追加したプロジェクトを開きます。

1. 左上に正しいプロジェクト名が表示されていることを確認する。
2. 左側の歯車 **⚙** → **使用量と請求** を開く。
3. 現在のプランが **Spark** または **料金なし** と表示されていることを確認する。

### Blazeと表示された場合

作業を止めてください。基盤のGoogle Cloudプロジェクトに請求先アカウントがリンクされています。
無料厳守なら、新しい請求なしプロジェクトを作り直します。

## 6. プロジェクトIDを記録する

1. Firebase Console左上の歯車 **⚙** を押す。
2. **プロジェクトの設定** を開く。
3. **全般** タブを開く。
4. **プロジェクトID** をメモする。

以降、次のように表記します。

```text
YOUR_PROJECT_ID = ここで確認したプロジェクトID
```

---

# 第3部: WebアプリをFirebaseへ登録する

## 7. Webアプリを登録する

ここでの「アプリ登録」は、すでに作成済みのReactアプリに接続情報を発行する操作です。
新しいソースコードが自動生成されるわけではありません。

1. Firebase Console左側の **プロジェクトの概要** を押す。
2. 画面中央にあるアプリアイコンから **Web（`</>`）** を押す。
   - アイコンがない場合は **アプリを追加** → **Web** を押す。
3. アプリのニックネームに `receipt-ocr-web` と入力する。
4. **このアプリのFirebase Hostingも設定する** というチェックがあれば、オフのままにする。
   - このリポジトリにはHosting設定がすでにあるためです。
5. **アプリを登録** を押す。
6. `firebaseConfig` というコードが表示される。
7. この画面を閉じず、次の値を一時的にメモする。

```javascript
const firebaseConfig = {
  apiKey: "...",
  authDomain: "YOUR_PROJECT_ID.firebaseapp.com",
  projectId: "YOUR_PROJECT_ID",
  storageBucket: "...",
  messagingSenderId: "...",
  appId: "..."
};
```

```
npm install firebase

// Import the functions you need from the SDKs you need
import { initializeApp } from "firebase/app";
// TODO: Add SDKs for Firebase products that you want to use
// https://firebase.google.com/docs/web/setup#available-libraries

// Your web app's Firebase configuration
const firebaseConfig = {
  apiKey: "...",
  authDomain: "YOUR_PROJECT_ID.firebaseapp.com",
  projectId: "YOUR_PROJECT_ID",
  storageBucket: "...",
  messagingSenderId: "...",
  appId: "..."
};

// Initialize Firebase
const app = initializeApp(firebaseConfig);
```


`measurementId` が表示されても、今回は使いません。

8. **コンソールに進む** を押す。

後から設定を見直す場合:

1. 歯車 **⚙** → **プロジェクトの設定** → **全般**。
2. 画面下部の **マイアプリ** までスクロールする。
3. `receipt-ocr-web` を選ぶ。
4. **SDKの設定と構成** → **構成** を選ぶ。

公式手順:

- [FirebaseへWebアプリを登録](https://firebase.google.com/docs/web/setup)

---

# 第4部: Googleログインを有効にする

## 8. Authenticationを開始する

1. Firebase Console左側の **構築** または **Build** を開く。
2. **Authentication** を押す。
3. 初回画面の **始める** または **Get started** を押す。
4. **ログイン方法** または **Sign-in method** タブを開く。
5. プロバイダ一覧の **Google** を押す。
6. **有効にする** スイッチをオンにする。
7. **プロジェクトのサポートメール** で本人のメールアドレスを選ぶ。
8. **保存** を押す。

公式手順:

- [WebでGoogleログインを有効化](https://firebase.google.com/docs/auth/web/google-signin)

## 9. 承認済みドメインを確認する

1. Authentication画面の **設定** を開く。
2. **承認済みドメイン** または **Authorized domains** を開く。
3. 次のドメインがあることを確認する。

```text
YOUR_PROJECT_ID.firebaseapp.com
YOUR_PROJECT_ID.web.app
```

`web.app` がなければ **ドメインを追加** から追加します。

Macでローカル画面のGoogleログインも試す場合は、次も追加します。

```text
localhost
```

新しいFirebaseプロジェクトでは、`localhost` が自動登録されない場合があります。

## 10. Authenticationでの許可と家計簿の許可は別だと理解する

Googleログインを有効にすると、Googleアカウントを持つ人は認証画面までは進めます。
しかし、家計簿データはFirestore Security Rulesで別途保護します。

```text
Authentication: Google本人であることを確認
Firestore Rules: そのメールアドレスが家族の許可リストにあるか確認
```

妻のメールアドレスは後でMacのコマンドから許可リストへ追加します。

---

# 第5部: Firestoreデータベースを作る

## 11. Firestore Databaseを開始する

1. Firebase Console左側の **構築 / Build** を開く。
2. **Firestore Database** を押す。
3. **データベースを作成** を押す。

画面によって項目の順序が異なりますが、以下を選びます。

### エディションを聞かれた場合

**Standard** を選びます。EnterpriseやMongoDB互換は選びません。

### データベースIDを聞かれた場合

**`(default)`** を選ぶか、初期値のままにします。

このアプリはデフォルトデータベースへ接続します。別名のデータベースは作らないでください。

### セキュリティルールの開始モード

**本番環境モード / Start in production mode** を選びます。

本番環境モードでは、最初はWebブラウザからの読み書きがすべて拒否されます。後ほど、この
リポジトリの `firestore.rules` をデプロイして、家族だけに許可します。

**テストモードは選ばないでください。** テストモードは一時的に第三者から読み書き可能になる
ルールを作るため、家計データには不適切です。

### ロケーション

選択できる場合は次を選びます。

```text
asia-northeast1 (Tokyo)
```

日本からの利用で遅延を抑えるためです。

注意:

- Firestoreのロケーションは作成後に変更できません。
- 既存Google Cloudプロジェクトのデフォルトロケーションがすでに決まっている場合、選択欄が
  表示されないか、別の場所で固定されることがあります。
- すでに固定されている場合は、表示されたロケーションのまま続行できます。

4. 選択内容を確認する。
5. **作成** を押す。
6. 数十秒待ち、Firestoreの **データ** タブが表示されれば完了。

まだデータがないため、コレクション一覧は空で正常です。

公式手順:

- [Cloud Firestoreクイックスタート](https://firebase.google.com/docs/firestore/quickstart)
- [Firestoreロケーション](https://firebase.google.com/docs/firestore/locations)

---

# 第6部: Mac用サービスアカウント鍵を取得する

## 12. 秘密鍵をダウンロードする

この鍵は、MacBookのOCRプログラムがFirestoreへデータを書き込むために使います。
Webアプリ用の `apiKey` とは異なり、強い管理権限を持つ秘密情報です。

1. Firebase Console左上の歯車 **⚙** を押す。
2. **プロジェクトの設定** を開く。
3. **サービスアカウント** タブを開く。
4. **Firebase Admin SDK** が選ばれていることを確認する。
5. Pythonのコード例が見えても、コピーする必要はない。
6. **新しい秘密鍵の生成** または **Generate new private key** を押す。
7. 警告を読み、もう一度 **キーを生成** を押す。
8. JSONファイルがダウンロードされる。

公式手順:

- [Firebase Admin SDKのサービスアカウント設定](https://firebase.google.com/docs/admin/setup)

## 13. 秘密鍵を安全な場所へ移動する

ターミナルを開きます。

```bash
cd /Users/k-hirata/Documents/receipt-ocr
mkdir -p secrets
```

Finderで **ダウンロード** フォルダを開き、今ダウンロードしたJSONファイルを探します。
ファイル名は次のような形式です。

```text
YOUR_PROJECT_ID-firebase-adminsdk-xxxxx-1234567890.json
```

そのファイルをFinderで次のフォルダへ移動します。

```text
/Users/k-hirata/Documents/receipt-ocr/secrets/
```

移動後、ファイル名を次に変更します。

```text
firebase-service-account.json
```

最終的な絶対パス:

```text
/Users/k-hirata/Documents/receipt-ocr/secrets/firebase-service-account.json
```

ターミナルで存在を確認します。

```bash
ls -l secrets/firebase-service-account.json
chmod 600 secrets/firebase-service-account.json
```

絶対にしないこと:

- JSONの中身をチャットやメールに貼らない
- Google Driveへ置かない
- `web-app/` へ置かない
- Gitへコミットしない
- Firebase Hostingへアップロードしない

このリポジトリでは `secrets/` を `.gitignore` に登録済みです。

---

# 第7部: Macの開発環境を準備する

## 14. ターミナルでプロジェクトへ移動する

```bash
cd /Users/k-hirata/Documents/receipt-ocr
pwd
```

次が表示されることを確認します。

```text
/Users/k-hirata/Documents/receipt-ocr
```

以降、特に記載がなければこのフォルダでコマンドを実行します。

## 15. Node.jsとnpmを確認する

```bash
node --version
npm --version
```

両方にバージョン番号が表示されれば問題ありません。Firebase CLIはNode.js 18以降が必要です。

`command not found` になった場合はNode.jsを先にインストールする必要があります。

公式要件:

- [Firebase CLIのインストール](https://firebase.google.com/docs/cli)

## 16. Firebase CLIをインストールする

```bash
npm install -g firebase-tools
```

完了後、確認します。

```bash
firebase --version
```

数字が表示されれば成功です。

### 権限エラーになる場合

`EACCES` や `permission denied` が表示された場合は、無理に `sudo npm` を使わず、Firebase公式の
macOS用自動インストーラを検討してください。

```bash
curl -sL https://firebase.tools | bash
```

## 17. Firebase CLIへログインする

```bash
firebase login
```

1. ブラウザが自動で開く。
2. Firebase Consoleで使った本人のGoogleアカウントを選ぶ。
3. Firebase CLIからのアクセス確認画面で内容を確認して許可する。
4. ターミナルへ戻る。

次のように表示されれば成功です。

```text
Success! Logged in as your-email@example.com
```

プロジェクト一覧を確認します。

```bash
firebase projects:list
```

第2部で準備したプロジェクトIDが一覧にあれば成功です。

## 18. このリポジトリとFirebaseプロジェクトを接続する

```bash
firebase use --add
```

対話形式で質問されます。

1. 上下キーで今回のプロジェクトIDを選ぶ。
2. Enterを押す。
3. エイリアス名を聞かれたら `default` と入力する。

完了後に確認します。

```bash
firebase use
```

今回のプロジェクトIDに `default` が付いていれば成功です。

重要:

- このリポジトリには `firebase.json` と `firestore.rules` がすでにあります。
- **`firebase init` は実行しないでください。** 既存設定を上書きする可能性があります。

## 19. Python環境へFirebase Admin SDKを導入する

最初に仮想環境が存在するか確認します。

```bash
cd /Users/k-hirata/Documents/receipt-ocr
ls -ld .venv
```

`No such file or directory` と表示された場合は、仮想環境を新しく作成します。

```bash
python3 -m venv .venv
```

作成後、仮想環境を有効にします。macOS標準Pythonから作った仮想環境には古い`pip`が
入ることがあるため、先に`pip`を更新してからFirebase Admin SDKを導入します。

```bash
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
```

有効になると、ターミナルの行頭に `(.venv)` が表示されます。

`Directory cannot be installed in editable mode` や
`editable mode currently requires a setuptools-based build` と表示された場合も、`pip`の更新後に
`python -m pip install -e .` を再実行してください。

確認します。

```bash
python -c "import firebase_admin; print(firebase_admin.__version__)"
```

バージョン番号が表示されれば成功です。

---

# 第8部: アプリ設定ファイルを編集する

## 20. `config/config.json` にcloud設定を追加する

Finderまたはエディタで次のファイルを開きます。

```text
/Users/k-hirata/Documents/receipt-ocr/config/config.json
```

トップレベルへ次の `cloud` ブロックを追加します。

```json
"cloud": {
  "enabled": true,
  "household_id": "hirata-household",
  "household_name": "わが家の家計簿",
  "service_account_path": "secrets/firebase-service-account.json"
}
```

JSONでは、前のブロックとの間にカンマが必要です。全体の一部は次の形になります。

```json
{
  "paths": {
    "inbox_dir": "data/inbox"
  },
  "ocr": {
    "backend": "macos_vision"
  },
  "cloud": {
    "enabled": true,
    "household_id": "hirata-household",
    "household_name": "わが家の家計簿",
    "service_account_path": "secrets/firebase-service-account.json"
  },
  "categories": {
    "食費": ["牛乳"]
  }
}
```

既存の `paths`、`ocr`、`drive`、`parser`、`categories` は削除しないでください。

保存後、JSONの文法を確認します。

```bash
python3 -m json.tool config/config.json > /dev/null
```

何も表示されなければ正常です。行番号付きのエラーが出た場合は、その付近のカンマや引用符を
確認してください。

## 21. Webアプリ用 `.env.local` を作る

```bash
cd /Users/k-hirata/Documents/receipt-ocr/web-app
cp .env.example .env.local
open -e .env.local
```

TextEditが開きます。第3部で確認した `firebaseConfig` を次のように対応させます。

| Firebaseの表示 | `.env.local` |
|---|---|
| `apiKey` | `VITE_FIREBASE_API_KEY` |
| `authDomain` | `VITE_FIREBASE_AUTH_DOMAIN` |
| `projectId` | `VITE_FIREBASE_PROJECT_ID` |
| `storageBucket` | `VITE_FIREBASE_STORAGE_BUCKET` |
| `messagingSenderId` | `VITE_FIREBASE_MESSAGING_SENDER_ID` |
| `appId` | `VITE_FIREBASE_APP_ID` |

完成形:

```dotenv
VITE_FIREBASE_API_KEY=実際のapiKey
VITE_FIREBASE_AUTH_DOMAIN=YOUR_PROJECT_ID.firebaseapp.com
VITE_FIREBASE_PROJECT_ID=YOUR_PROJECT_ID
VITE_FIREBASE_STORAGE_BUCKET=表示されたstorageBucket
VITE_FIREBASE_MESSAGING_SENDER_ID=表示されたmessagingSenderId
VITE_FIREBASE_APP_ID=表示されたappId
VITE_HOUSEHOLD_ID=hirata-household
```

注意:

- `=` の右側を引用符で囲む必要はありません。
- 行末にカンマを付けません。
- `VITE_HOUSEHOLD_ID` は `config/config.json` と完全に同じ値にします。
- `.env.local` はGit管理対象外です。

保存したらTextEditを閉じ、プロジェクトルートへ戻ります。

```bash
cd /Users/k-hirata/Documents/receipt-ocr
```

---

# 第9部: 世帯・許可リスト・カテゴリを作る

## 22. 本人と妻のメールアドレスを確認する

Googleログインに使う正確なメールアドレスを準備します。

```text
本人: owner@example.com
妻:   wife@example.com
```

Gmail以外のGoogleアカウントを使う場合も、Googleログイン画面に表示されるメールアドレスを
指定します。

## 23. 初期データを作成する

メールアドレスを実際の値へ置き換えて実行します。

```bash
PYTHONPATH=src .venv/bin/python -m receipt_ocr bootstrap-cloud \
  --email 本人のメールアドレス \
  --email 妻のメールアドレス
```

成功時:

```text
bootstrap=complete
```

このコマンドは次を作成します。

- 世帯 `hirata-household`
- 本人と妻の許可メール
- 食費、日用品、消耗品、調整、収入等の初期カテゴリ

## 24. Firebase Consoleで作成結果を見る

1. Firebase Consoleへ戻る。
2. **Firestore Database** を開く。
3. **データ** タブを開く。
4. `households` コレクションが表示されていることを確認する。
5. `households` を押す。
6. `hirata-household` ドキュメントを押す。
7. サブコレクションとして `categories` や `allowed_emails` が見えることを確認する。

これがFirestoreの基本UIです。

```text
左列: コレクション
中央: 選択したコレクション内のドキュメント
右列: 選択したドキュメントのフィールド
```

`allowed_emails` は後でSecurity RulesによりWebアプリから直接読めなくなりますが、管理者として
Firebase Consoleからは確認できます。

---

# 第10部: Security Rulesとインデックスを公開する

## 25. Firestore設定をデプロイする

プロジェクトルートで実行します。

```bash
cd /Users/k-hirata/Documents/receipt-ocr
firebase deploy --only firestore
```

このコマンドは次の2つを公開します。

- `firestore.rules`: 本人・妻だけに世帯データへのアクセスを許可
- `firestore.indexes.json`: 確認待ち一覧等に必要な検索インデックス

成功時は最後に次のような表示が出ます。

```text
Deploy complete!
```

## 26. Firebase ConsoleでRulesを確認する

1. Firebase Consoleの **Firestore Database** を開く。
2. **ルール / Rules** タブを開く。
3. 先頭に `rules_version = '2';` があることを確認する。
4. `allowed_emails` や `householdMember` を含むルールが表示されていることを確認する。

Firebase Consoleのルール編集画面で直接変更しないでください。次回のCLIデプロイで上書きされます。

---

# 第11部: Webアプリをテストして公開する

## 27. Web依存関係とビルドを確認する

```bash
cd /Users/k-hirata/Documents/receipt-ocr/web-app
npm install
npm test
npm run build
```

確認ポイント:

- `npm test` の最後にテスト成功が表示される
- `npm run build` の最後に `built in ...` が表示される
- JavaScriptサイズの警告だけで終了コードが成功なら問題ない

## 28. Mac上で画面を確認する

```bash
npm run dev
```

次のようなURLが表示されます。

```text
http://localhost:5173/
```

ブラウザで開きます。

確認すること:

1. 「わが家の家計簿」と表示される。
2. **Googleでログイン** を押す。
3. 本人のGoogleアカウントを選ぶ。
4. 家計簿のホーム画面が表示される。

`auth/unauthorized-domain` が出る場合は、第4部の承認済みドメインへ `localhost` を追加します。

確認後、ターミナルで `Control + C` を押して開発サーバーを停止します。

## 29. Firebase Hostingへ公開する

プロジェクトルートへ戻り、公開します。

```bash
cd /Users/k-hirata/Documents/receipt-ocr
firebase deploy --only hosting
```

成功時は次のようなURLが表示されます。

```text
Hosting URL: https://YOUR_PROJECT_ID.web.app
```

このURLはインターネット上からアクセスできます。HTMLやJavaScriptは公開されますが、家計データは
GoogleログインとFirestore Security Rulesで保護されます。

公式手順:

- [Firebase Hostingクイックスタート](https://firebase.google.com/docs/hosting/quickstart)

## 30. 公開画面を本人のアカウントで確認する

1. 表示された `https://YOUR_PROJECT_ID.web.app` を開く。
2. **Googleでログイン** を押す。
3. 本人のGoogleアカウントを選ぶ。
4. ホーム画面が表示されることを確認する。
5. **取引** → **手入力** からテスト支出を1件登録する。
6. ホームへ戻り、支出へ反映されることを確認する。
7. 不要なら取引一覧からテスト取引を削除する。

## 31. 妻のAndroidで確認する

1. 公開URLを妻のAndroidへ送る。
2. ChromeでURLを開く。
3. **Googleでログイン** を押す。
4. 第9部で許可した妻のGoogleアカウントを選ぶ。
5. 同じ家計簿が表示されることを確認する。

許可していない別アカウントでログインした場合は、データ取得が `permission-denied` になります。
これは正常なアクセス拒否です。

---

# 第12部: 既存SQLiteデータを移行する

## 32. 既存レシートを確認待ちとして送る

この操作は一度だけ実行します。

```bash
cd /Users/k-hirata/Documents/receipt-ocr
PYTHONPATH=src .venv/bin/python -m receipt_ocr migrate-cloud
```

成功例:

```text
synced=3 failed=0
```

既存SQLiteの3件は、内容に問題がなくても安全のため **確認待ち** として移行されます。

## 33. Webアプリで既存レシートを確認する

1. 公開した家計簿を開く。
2. **確認** を開く。
3. 移行したレシートを1件選ぶ。
4. 店名、日付、合計、明細、カテゴリを確認する。
5. 差額がある場合は明細を修正する。
6. 明細合計とレシート合計が一致したら **確定する** を押す。
7. ホームの月次集計へ反映されることを確認する。

同じ移行コマンドを再実行しても、Firestore上でレシートは重複しません。同期状態はSQLiteの
`cloud_sync` テーブルへ保存されます。

---

# 第13部: 日常の使い方

## 34. 新しいレシートをOCRして同期する

```bash
cd /Users/k-hirata/Documents/receipt-ocr
PYTHONPATH=src .venv/bin/python -m receipt_ocr run --sync-drive
PYTHONPATH=src .venv/bin/python -m receipt_ocr sync-cloud
```

結果:

- 金額一致・分類済み: 自動確定され、ホームへ反映
- 未分類・必須項目不足・説明できない11円以上の差額: **確認** に表示
- 同期失敗: SQLiteに失敗状態を保存し、次回 `sync-cloud` で再送

Webで修正した商品カテゴリはFirestoreへ分類ルールとして保存され、次回OCR実行前にMacへ取得されます。

## 35. Webアプリを更新して再公開する

ソースコードを変更した場合だけ実行します。

```bash
cd /Users/k-hirata/Documents/receipt-ocr/web-app
npm test
npm run build
cd ..
firebase deploy --only hosting
```

Firestore Rulesを変更した場合:

```bash
firebase deploy --only firestore
```

---

# トラブルシューティング

## Firebase Consoleに既存Google Cloudプロジェクトが出ない

確認すること:

- Firebase ConsoleとGoogle Cloud Consoleで同じGoogleアカウントを使っているか
- そのアカウントが既存プロジェクトのオーナーまたは十分な権限を持っているか
- Firebase利用規約へ同意済みか

`403 PERMISSION_DENIED` の場合は権限または利用規約が原因であることが多いです。

## SparkではなくBlazeになっている

基盤のGoogle Cloudプロジェクトへ請求先アカウントがリンクされています。無料厳守なら作業を止め、
請求なしの新規Firebaseプロジェクトを作ります。

## `firebase: command not found`

Firebase CLIがインストールされていないか、ターミナルを開き直す必要があります。

```bash
npm install -g firebase-tools
firebase --version
```

## `firebase projects:list` にプロジェクトが出ない

```bash
firebase logout
firebase login
firebase projects:list
```

Firebase Consoleを操作した本人アカウントでログインし直します。

## `cloud.enabled ... are required`

`config/config.json` の `cloud` ブロックがない、`enabled` が `false`、またはキー名が間違っています。

## サービスアカウントJSONが見つからない

```bash
cd /Users/k-hirata/Documents/receipt-ocr
ls -l secrets/firebase-service-account.json
```

見つからない場合は、ダウンロードしたJSONの移動場所とファイル名を確認します。

## `ModuleNotFoundError: firebase_admin`

```bash
cd /Users/k-hirata/Documents/receipt-ocr
. .venv/bin/activate
pip install -e .
```

## `permission-denied` と表示される

主な原因:

- Firestore Rulesをまだデプロイしていない
- ログインしたメールアドレスと許可したメールアドレスが異なる
- `.env.local` の `VITE_HOUSEHOLD_ID` と `config/config.json` の `household_id` が異なる
- 別のFirebaseプロジェクトへWebアプリをデプロイした

確認コマンド:

```bash
firebase use
```

許可メールを追加し直す場合:

```bash
PYTHONPATH=src .venv/bin/python -m receipt_ocr bootstrap-cloud \
  --email 本人のメールアドレス \
  --email 妻のメールアドレス
```

## `auth/unauthorized-domain`

Firebase Consoleで次を開きます。

```text
Authentication → 設定 → 承認済みドメイン
```

アクセス元のドメインを追加します。

- ローカル確認: `localhost`
- 公開画面: `YOUR_PROJECT_ID.web.app`

## Googleログインのポップアップが開かない

- ブラウザのポップアップブロックを解除する
- シークレットモードではなく通常タブで試す
- AndroidではChromeで開く
- 別Googleアカウントが選択されていないか確認する

## Firestoreのインデックスが必要というエラー

```bash
firebase deploy --only firestore
```

デプロイ直後はインデックス作成に数分かかることがあります。Firebase Consoleの
**Firestore Database → インデックス** で状態が **有効** になるまで待ちます。

## `npm run build` でFirebase設定エラー

`web-app/.env.local` が存在し、6つのFirebase設定値がすべて入っていることを確認します。

```bash
cd /Users/k-hirata/Documents/receipt-ocr/web-app
ls -la .env.local
```

値を直した後は、必ずもう一度ビルドします。

```bash
npm run build
```

## Webで直した値がMacから再び上書きされないか

上書きされません。Macからの同期はFirestoreに同じレシートがすでに存在する場合、Webで修正された
クラウド側データを保持します。

---

# 完了チェックリスト

## Firebase Console

- [ ] 正しいプロジェクトを開いている
- [ ] Sparkプランである
- [ ] Webアプリ `receipt-ocr-web` を登録した
- [ ] AuthenticationでGoogleを有効にした
- [ ] Firestore Standard・`(default)` を作成した
- [ ] Firestoreは本番環境モードで開始した
- [ ] サービスアカウントJSONをダウンロードした

## MacBook

- [ ] `secrets/firebase-service-account.json` が存在する
- [ ] `config/config.json` に `cloud` 設定がある
- [ ] `web-app/.env.local` にFirebase設定値がある
- [ ] `firebase use` が正しいプロジェクトを示す
- [ ] `bootstrap-cloud` が成功した
- [ ] `firebase deploy --only firestore` が成功した
- [ ] `npm test` と `npm run build` が成功した
- [ ] `firebase deploy --only hosting` が成功した

## 動作確認

- [ ] 本人のGoogleアカウントでログインできる
- [ ] 妻のGoogleアカウントでログインできる
- [ ] 許可していないアカウントは家計データを読めない
- [ ] 手入力した支出がホームへ反映される
- [ ] 既存レシート3件が確認画面に表示される
- [ ] 確定したレシートが月次集計へ反映される

すべて確認できればFirebase家計簿の初期設定は完了です。
