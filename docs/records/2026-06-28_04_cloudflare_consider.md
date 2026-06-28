# receipt-ocrでCloudflare無料機能を活用する検討

- 作成日: 2026-06-28
- ステータス: 検討案（未実装・未採用）
- 文書種別: 構成検討
- 関連: [MacBookを使わない原則無料OCR構成の検討](2026-06-28_03_CONSIDER.md)

## 目的

Cloudflareが提供する無料機能を、次の目標に利用できるか検討する。

- MacBookを起動せずにレシートを処理する
- 通常利用で費用を発生させない
- Google Cloud Vision APIは月1,000ユニットの無料枠内で使う
- Androidアプリ、Google Drive、Firestore、家計簿Webアプリを安全に連携する
- Oracle Cloud Always Free VMの運用負担または停止リスクを補う

## 結論

Cloudflareは活用できるが、**現時点ではOCRワーカーの主実行基盤としてOracle VMを置き換えない**方が
よい。既存のPython解析コードをそのまま動かせるOracle VMに対し、Cloudflare Workers Freeプランは
1回あたりのCPU時間が10msに制限されるため、Google認証、Visionレスポンスの解析、既存Python処理の
実行を安定して収められるか実測が必要である。

当面の採用候補は次の2つ。

1. **Cloudflare Pages**: 家計簿Webアプリの静的ホスティング候補
2. **Cloudflare Tunnel**: OCI VMへ管理画面やSSHを公開する必要が生じた場合の安全な経路

将来の実証候補は次の構成。

```text
Android
  -> 認証付きCloudflare Worker
  -> R2へ画像保存
  -> R2 Event Notification
  -> Cloudflare Queue
  -> Queue Consumer Worker
  -> Google Cloud Vision API
  -> Cloud Firestore
```

このCloudflareネイティブ構成は、実現できればGoogle DriveとOCI VMの両方をOCR経路から外せる。
ただしAndroid認証の追加、既存Python処理の移植、Workersの10ms CPU上限検証が必要なため、最初から
本番構成にはしない。

## 無料で使える主な機能と適合性

2026-06-28時点のCloudflare公式資料に基づく。

| 機能 | Freeプランの主な範囲 | 今回の用途 | 評価 |
| --- | --- | --- | --- |
| Workers | 100,000リクエスト/日、CPU 10ms/回、メモリ128MB、外部サブリクエスト50回/実行 | Drive監視、Vision呼び出し、API | 条件付きで利用可能。CPU上限が厳しい |
| Cron Triggers | Freeはアカウントあたり最大5個、Cron実行もCPU 10ms | Driveの定期確認 | 小規模PoCには十分 |
| Pages / Static Assets | 静的アセットへのリクエストは無料・無制限。Freeは月500ビルド | React家計簿の配信 | 適合性が高い |
| R2 Standard | 10GB-month、Class A 100万回/月、Class B 1,000万回/月、外向き転送無料 | レシート画像の一時保管 | 適合性が高いが、超過課金に注意 |
| Queues | 10,000操作/日、保持24時間 | 画像処理の非同期化・再試行 | 家庭用途には十分 |
| D1 | 500万行読取/日、10万行書込/日、合計5GB | OCRジョブ、月次使用数 | 十分だがFirestoreと役割が重複 |
| Turnstile | Free、最大20ウィジェット、チャレンジ回数無制限 | 公開WebフォームのBot対策 | 管理Webには有用。Android API認証の代替にはならない |
| Tunnel | すべてのプランで利用可能。originから外向き接続 | OCI VMの管理経路 | 外部公開が必要な場合に有用 |
| Workers AI | Free枠あり | OCR代替 | 今回は採用しない。Cloud Visionとの比較対象を増やさない |

Workersでは外部APIを待つ時間はCPU時間に含まれない。一方、JWT生成、JSON処理、レシート解析、
Firestore向けデータ生成はCPU時間に含まれる。Cloudflareの資料でも、認証や大きなデータの解析を行う
処理は10～20msになることがあるとしており、Freeプランの10msを超える可能性がある。

## 活用案A: PagesでWebアプリを配信する

現在の `web-app/` はViteで静的ビルドできるため、`web-app/dist/` をCloudflare Pagesへそのまま
デプロイできる。FirestoreとFirebase Authenticationはブラウザから引き続き利用する。

必要な変更:

- Cloudflare PagesへGitHubリポジトリを接続する
- ビルドコマンドを `npm run build` にする
- 出力先を `web-app/dist` にする
- Firebase設定値をPagesの環境変数へ登録する
- Firebase Authenticationの承認済みドメインへ `*.pages.dev` または独自ドメインを追加する
- SPAのルーティングが必要ならフォールバック設定を確認する

利点:

- 静的アセットへのリクエストが無料・無制限
- Git pushから自動デプロイできる
- Firebase Hostingの転送量を使わない
- CloudflareのCDNから配信される

欠点:

- Firebase Hostingも現在の家庭用途では無料枠内なので、金額面の改善はほぼない
- ホスティング先が1つ増え、設定と障害箇所が増える
- OCR処理には影響しない

判断: **利用可能だが優先度は低い**。Firebase Hostingに問題がなければ移行しない。

## 活用案B: TunnelでOCI VMを保護する

03の構成ではOCI VMは外向き通信だけを行い、公開HTTP APIを持たない。その場合、Cloudflare Tunnelは
必須ではない。将来、管理画面、手動再実行API、ログ閲覧画面をVMで提供したくなった場合に利用する。

```text
管理者ブラウザ
  -> Cloudflare Access
  -> Cloudflare Tunnel
  -> OCI VMのlocalhost管理画面
```

`cloudflared` がOCI VMからCloudflareへ外向き接続するため、VMの管理画面用ポートをインターネットへ
直接開かずに済む。

判断: **公開管理画面を作るときだけ採用**。現在のポーリングワーカーだけなら導入しない。

## 活用案C: WorkerのCronでDriveを監視する

OCI VMの代わりに、Cron Triggerで数分おきにWorkerを起動する。

```text
Cron Trigger
  -> WorkerがDrive APIを確認
  -> 未処理ファイルをQueueへ投入
  -> Queue Consumerが画像を取得
  -> Cloud Vision API
  -> Firestore
```

ネットワーク待ち時間はCPU時間に含まれないため、Drive、Vision、FirestoreへのHTTP通信自体はWorkersと
相性がよい。Workersは外部APIへ `fetch()` でき、サービスアカウント鍵はWorker Secretsへ保存できる。

問題点:

- FreeプランはCronもQueue Consumerも実行コードのCPU上限が厳しい
- GoogleサービスアカウントのJWT生成とトークン更新をWorkers向けに実装する必要がある
- 現在のPythonコードとGoogle公式Pythonクライアントをそのまま使えるとは限らない
- Python Workersは利用可能だが、Pyodide上のパッケージ互換性と3MBのWorkerサイズ上限を確認する必要がある
- 既存ロジックをTypeScriptへ移植すると、Mac版Pythonとの二重保守になる
- CronはFreeアカウント全体で最大5個

判断: **小さなPoCだけ行う候補**。以下がすべて成功した場合のみOCI VMの置き換えを再検討する。

1. WorkerからDrive APIへ認証できる
2. JPEG 1枚をVisionへ送り、レスポンスを取得できる
3. 店名、日付、合計の解析までCPU 10ms内に収まる
4. Firestoreへ冪等に書き込める
5. 同一Driveファイルを重複OCRしない

## 活用案D: R2とQueuesでDriveを置き換える

Cloudflareを最も活用する案。AndroidはDriveではなくR2へ画像をアップロードする。

### 処理フロー

1. AndroidがWorkerへアップロード許可を要求する。
2. Workerが端末・利用者を認証する。
3. Workerが有効期限の短いR2 Presigned URLを発行する。
4. AndroidがR2へJPEGを直接PUTする。
5. R2のobject-create通知がQueueへ入る。
6. Queue Consumer Workerが画像をVisionへ送る。
7. 解析結果をFirestoreへ書く。
8. 成功後にR2画像を削除するか、短い保存期限で自動削除する。

### 無料枠との相性

月1,000枚未満の家庭用途なら、10GB-month、Class A 100万回、Class B 1,000万回、Queue 10,000操作/日を
通常は大きく下回る。ただしR2は無料枠を超えた利用が課金対象になり得るため、画像サイズ、保存期間、
操作回数を監視する。

### セキュリティ上の必須条件

- R2の長期アクセスキーや固定Presigned URLをAndroidアプリへ埋め込まない
- Workerが認証後に短時間だけ有効なPresigned URLを発行する
- Firebase IDトークンなど、サーバー側で検証できる利用者認証を追加する
- 支払者、ファイルサイズ、MIME type、アップロード回数を検証する
- Worker SecretsへGoogleとR2の秘密情報を保存し、平文の環境変数やGitへ置かない
- R2バケットを公開しない
- ファイルIDとハッシュでVisionの重複呼び出しを防止する
- Visionの月次上限900件を維持する

### Android側の変更

現在のAndroidアプリはGoogle OAuth、Google Picker、Drive APIへ依存している。この案では次を変更する。

- Firebase Authenticationまたは専用端末認証を追加する
- Drive PickerとDrive OAuthを削除する
- WorkerからPresigned URLを取得する
- R2へ直接アップロードする
- アップロード成功とOCR処理成功を別の状態として表示する
- FirestoreまたはWorker APIから処理状態を確認する

判断: **長期的には魅力があるが、現時点では変更量が大きい**。Oracle VM構成を先に動かし、その後の
第2段階として検討する。

## 活用案E: D1で処理状態を管理する

D1の無料枠は家庭用途に十分だが、現在はFirestoreが次を管理できる。

- OCRジョブ
- 月次Vision利用数
- レシートと明細
- Web画面のレビュー状態

D1を追加すると、FirestoreとD1のどちらが正本かを決め、同期処理を実装する必要がある。

判断: **採用しない**。Cloudflareネイティブ構成へ全面移行する場合だけ再検討する。

## 活用案F: Turnstileを使う

Turnstileは無料で、WebフォームのBot対策には有効。ただし、AndroidアプリのAPI認証や利用者認証を
置き換えるものではない。

利用候補:

- 公開問い合わせフォーム
- 招待申請フォーム
- ログイン前に公開する手動アップロード画面

家計簿WebアプリはGoogleログインと世帯許可リストで制限されているため、現時点では不要。

判断: **公開フォームを作るまで採用しない**。

## 構成比較

| 観点 | Oracle VM + Drive | Workers + Drive | Workers + R2 + Queue |
| --- | --- | --- | --- |
| MacBook不要 | ○ | ○ | ○ |
| Android変更 | ほぼなし | ほぼなし | 大きい |
| 既存Python再利用 | 高い | 低～中 | 低～中 |
| 公開API | 不要 | 不要 | 必要 |
| サーバー保守 | 必要 | 不要 | 不要 |
| 無料枠の実行制限 | OCIの容量・回収 | CPU 10ms | CPU 10ms、R2、Queue |
| Drive依存 | あり | あり | なし |
| イベント駆動 | ポーリング | Cron + Queue | R2通知 + Queue |
| 実装量 | 中 | 中～大 | 大 |
| 現時点の推奨 | **採用候補** | PoC候補 | 将来候補 |

## 推奨ロードマップ

### 第1段階

[03の検討案](2026-06-28_03_CONSIDER.md)どおり、Oracle Always Free VMで既存Python処理を動かす。

- Android -> Driveを維持
- OCI VM -> Vision -> Firestoreを実装
- Vision月900件上限と重複防止を先に完成させる
- VMは外部公開しない

### 第2段階

Cloudflare Workerで最小PoCを行う。

- Cron 1個
- Driveのファイル一覧取得
- JPEG 1枚のVision OCR
- 店名、日付、合計だけ解析
- CPU時間をCloudflare Metricsで確認

10msを安定して超える場合は、Workers FreeでOCRワーカーを置き換えない。

### 第3段階

Oracle VMの保守や回収が実運用上の問題になった場合だけ、R2 + Queue + Worker構成を試す。
Androidの送信先変更は、この段階まで行わない。

## 課金事故を避ける方針

- CloudflareアカウントはWorkers Freeプランのまま使う
- Workers Freeで上限到達時に失敗する機能と、超過課金され得るR2を区別する
- R2を使う場合はStandard storageだけを使う
- R2の保存量を10GBより十分小さく保つ
- 処理成功後の画像を削除し、長期保管しない
- CloudflareとGoogleの利用量を毎月確認する
- Visionは900ユニットで停止する
- 公開Workerには認証、ファイルサイズ制限、レート制限を必須にする
- Workers Paidプランへ自動・不用意に変更しない
- 独自ドメインは必須にせず、購入費を発生させない

## 採用判断

現時点では次の判断とする。

- Cloudflare Pages: 利用可能。ただしFirebase Hostingから急いで移行しない
- Cloudflare Tunnel: OCIに公開管理機能が必要になった場合だけ利用する
- Workers Cron + Drive: 技術検証する価値あり。本番採用はCPU計測後
- R2 + Queues: 将来のDrive・OCI置き換え候補
- D1: Firestoreと重複するため採用しない
- Turnstile: 公開フォームを作るまで採用しない
- Workers AI: 今回は採用しない

CloudflareだけでMacBookとOracle VMの両方を不要にできる可能性はある。ただし、無料Workersの10ms CPU
上限がOCR後処理の安定性に対する最大の不確実性である。したがって、現在の推奨は **Oracle VMを主経路、
Cloudflareを補助・将来候補** とする。

## 公式資料（2026-06-28確認）

- [Workersの料金](https://developers.cloudflare.com/workers/platform/pricing/)
- [Workersの制限](https://developers.cloudflare.com/workers/platform/limits/)
- [Workers Cron Triggers](https://developers.cloudflare.com/workers/configuration/cron-triggers/)
- [WorkersのPython対応](https://developers.cloudflare.com/workers/languages/python/)
- [WorkersのPythonパッケージ](https://developers.cloudflare.com/workers/languages/python/packages/)
- [Workers Secrets](https://developers.cloudflare.com/workers/configuration/secrets/)
- [Workers Fetch API](https://developers.cloudflare.com/workers/runtime-apis/fetch/)
- [Pages Functionsの料金と静的アセット](https://developers.cloudflare.com/pages/functions/pricing/)
- [Pagesの制限](https://developers.cloudflare.com/pages/platform/limits/)
- [R2の料金と無料枠](https://developers.cloudflare.com/r2/pricing/)
- [R2へのアップロード](https://developers.cloudflare.com/r2/objects/upload-objects/)
- [R2 Event Notifications](https://developers.cloudflare.com/r2/buckets/event-notifications/)
- [Queuesの料金と無料枠](https://developers.cloudflare.com/queues/platform/pricing/)
- [D1の料金と無料枠](https://developers.cloudflare.com/d1/platform/pricing/)
- [Turnstileのプラン](https://developers.cloudflare.com/turnstile/plans/)
- [Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/)
