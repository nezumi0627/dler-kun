# dler-kun 全体監査と近代化設計

## 目的

利用者が指定したURLから、対応するメディアを速く安定して取得できる状態にする。検出、キュー、共通ネットワーク、各エンジン、CLIの境界を保ち、取得失敗を成功として報告しない。

## 対象範囲

- CLI、検出器、factory、application service、queue、cache、retry、progress、shared network。
- `gofile`、`gofilerun`、`mvfile`、`85xo`、`twimg`、`videy`、`mixixxx`、`linkex` の各エンジンと、内包する移行コード。
- 対応サイトの公開ページと公開クライアントJavaScriptから、現在のAPIパス、応答形式、埋め込み・メディアURLの解決手順を調べる。
- 型、lint、CLI、回帰テスト、実測に基づく性能検証。

## 対象外

- 認証、DRM、アクセス制御の突破。
- IPアドレス、アカウント、トークン、UAなどを切り替えてレート制限・IPブロックを回避する機能。
- ユーザーが作業前から持つ変更の破棄や上書き。
- 数値根拠のない同時実行数増加や、測定なしの「高速化」。

## 既知の制約と決定

- 既存アーキテクチャと依存関係を優先し、必要性を示せない新規依存は追加しない。
- サイトの変化はURLだけで推定せず、ホスト、ページ構造、API応答を根拠に判定する。
- HTTP 429やサイト固有のrate-limit応答を共通エラーとして識別する。`Retry-After`を尊重し、指定がない場合は指数バックオフとジッターを使う。長い待機が必要なら早期再試行せず、待機時間を利用者に返す。
- 公開資料にない制限値は推測しない。Gofileの現行API文書は制限値を非公開とし、IP・アカウント単位の429とバックオフを案内している。反復超過はIP banにつながり得るため、回避ではなくリクエスト量制御と停止で扱う。
- `src/dler_kun/vendor/twimg/download_twitter_media.py` は外部ツールとして扱い、まずadapter側で修正する。
- 作業開始時の未コミット差分（`detector.py`、`engines/mvfile/adapter.py`、`engines/mvfile/api.py`）を保持する。gofile.plは現行公開ページが他のfun800系と同じ`/flow/land-page/...`経路を参照していることを確認済み。

## 監査で確認した問題

以下は静的コードと呼び出し元を確認した問題。行番号は監査時点のもの。

### 優先度 高

1. `src/dler_kun/detector.py:36` — mvfileとtwimgが`twimg-media.com`、`tweetfile.com`、`twimg.jp`を重複して持ち、先に評価されるmvfileへ誤配送する。ドメインごとの実バックエンドを確認してルールを分離する。
2. `src/dler_kun/app.py:174` — 複数URLの保存先IDがホストを含まないパス末尾だけで決まり、異なるホストの同一末尾URLが並列実行時に衝突する。
3. `src/dler_kun/net.py:172-186` — `fetch_text`がタイムアウト引数を受け取るが、curlプロセスに適用しない。
4. `src/dler_kun/app.py:479-483`、`src/dler_kun/managers.py:450` — キャンセル確認と完了状態更新が別ロック区間にあり、完了とキャンセルが競合すると終端状態を上書きできる。
5. `src/dler_kun/engines/mixixxx/fast.py:404-423` — HLSセグメントに欠落があると、成功した実ファイル名ではなく成功数から連番を再構成し、誤ったセグメントを結合する。
6. `src/dler_kun/engines/85xo/fast.py:261-276` — 並列ページ取得の1件の例外がFuture全体を失敗させ、他ページの結果も返らない。

### 優先度 中

7. `src/dler_kun/app.py:286-289` — `days or 10`により明示した`days=0`が既定の10日に置き換わる。
8. `src/dler_kun/engines/mixixxx/adapter.py:186` — 全動画の取得に失敗して`files=[]`でも、件数不足判定を通らず成功状態を返し得る。
9. `src/dler_kun/engines/twimg/adapter.py:91` — subprocessが成功しても、保存ファイルを`DownloadResult.files`へ反映しない。
10. `src/dler_kun/engines/mixixxx/adapter.py:83` — ffmpeg不足を一般的な`download_failed`へ変換し、`dependency_missing`として報告しない。
11. `src/dler_kun/engines/linkex/adapter.py:45` — `invalid_request`を`network_error`へ分類する。
12. `src/dler_kun/engines/gofile/gofile_dl/downloader/go_file_api.py:353-356` — 502/503/504再試行前に応答を解放しない。
13. `src/dler_kun/engines/gofile/gofile_dl/downloader/go_file_api.py:115-124, 343-354` — Retry-Afterを数値秒だけとして解釈し、最大120秒で切り詰めてから再試行する。HTTP-date形式や120秒超を受けた場合に、サーバー指示より早く再試行し得る。

### 要確認

- `src/dler_kun/engines/linkex/adapter.py:58-61` — 共有フォルダ取得がpage_size=100で1回のみ。現在のAPIがページングをどう示すかを公開ページと応答形で確かめる。
- `src/dler_kun/engines/linkex/adapter.py`のAPIホストと、現在のl2e.clickページに含まれるAPI参照が別経路に見える。役割が異なる可能性があるため、サンプルページの実応答で照合する。
- `85xo.com`、`mvfile.com`、`gofile.rocks`、`gofile.video`、`imagedist.com`、`twimg.jp`は調査環境から名前解決できなかった。最新ページを確認できるまで互換性を断定しない。

## 現行サービス調査の初期結果

- Gofile公式API文書: `https://gofile.io/api`。応答の`status`をHTTP statusと別に確認すること、429と`error-rateLimit`、IP・アカウント単位の制限、レート制限値が非公開であることを明記。現在の移行コードが使うwebsite tokenや内部署名は公開API契約ではないため、公開仕様へ置き換え可能な範囲と非対応境界を調べる。
- gofile.bar / gofile.pl / tweetfile.com / image-share.cc / tweetplay.com / twimg-media.com: 公開JavaScriptに`/flow/land-page/getInfo`、`/flow/land-page/list_by_links_page`、`/flow/net-disk/putPassword`がある。fun800系adapterの応答パーサと照合する。
- gofile-douga.com: 公開JavaScriptにランキング・新着・ダウンロード検査APIへの参照がある。既存のランキングAPIパラメータと照合する。
- Videy: 公開クライアントに`api.videy.co`と`cdn.videy.co`の参照がある。現adapterのID抽出と直リンク組み立てを現在のサンプルページで検証する。
- mixi-xxx.cc / l2e.click / 85po.net / gofile.website / gofile.run: ページ応答または静的scriptの取得はできたが、現adapterとの全機能照合にはページ別のサンプルURLが必要。

## 実装順

1. 既存差分を保持したまま、出力衝突・キャンセル遷移・timeout・`days=0`を共通境界で直す。
2. エンジンの失敗状態とファイル一覧を契約に合わせる。HLS結合は実取得ファイル一覧から生成し、欠落を成功扱いしない。
3. GoFileと他サービスのHTTPエラーを共通分類へ変換し、rate limitは待機指示を守る。上限を超える応答では再試行せず停止する。
4. 各サービスの検出競合・API応答形・ページング・直リンク/HLS分岐をfixtureで固定し、確認済み仕様の回帰テストを作る。
5. basedpyrightの既存エラーを解消し、公開APIと例外境界を整理する。不要コード削除は参照と動作を確認して行う。
6. ベンチマークと同一条件の実測で、各エンジンの実効同時数・接続再利用・I/O待ちを比較する。測定値をもとに性能を調整する。

## 完了条件

- 既知の高優先度問題に回帰テストがあり、失敗時に誤成功・上書き・無期限待機が起きない。
- 各対応エンジンが検出・取得・失敗分類・出力一覧を共通契約で返す。未確認のサイト変更は成功扱いせず、診断可能なunsupported/network/dependency errorとして返す。
- GoFileのrate limit応答でサーバー指定より早く再試行しない。レート制限回避のためのIP/アカウント切替を追加しない。
- `ruff check src/dler_kun`、`basedpyright`、CLI help、関連テストが通る。
- 最適化前後の測定条件と結果を残し、安定性を落とさず性能が改善した箇所だけ採用する。

## 承認後に残る決定

- サービスから実アクセスできるサンプルURLがない場合は、静的fixtureで仕様を固定し、実サイト互換性を「未検証」と明示する。
- 安定性を優先するため、レート制限時の自動再試行はサーバー指定待機が設定上限内の場合に限る。上限外は停止し、ユーザーが後で再実行する。
