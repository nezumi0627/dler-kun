# アーキテクチャ

`dler-kun` はダウンローダー固有の処理を **Engine Adapter** の背後に閉じ込め、共有のアプリケーション層を **Manager** に集約します。既存実装は `src/dler_kun/vendor/` の vendored コピーをそのまま利用し、内部ロジックは書き換えません。

## 責務フロー

```text
CLI (__main__.py)
  -> DlerKunApp (app.py)
  -> ServiceDetector / DownloaderFactory
  -> IDownloader Engine Adapter
  -> Vendored Downloader (vendor/)
  -> Managers (config, queue, log, progress, history, cache, retry, proxy, cookies)
```

### レイヤー説明

| レイヤー | 役割 |
|----------|------|
| **CLI** | 引数解析、人間向けサマリー / `--json` 出力。アプリケーションサービスのみ呼び出す |
| **DlerKunApp** | ジョブ作成、リトライ、キャンセル、エンジン登録 |
| **ServiceDetector** | URL からエンジン ID を判定 |
| **DownloaderFactory** | 登録済みエンジンの lookup |
| **Engine Adapter** | vendored 実装への橋渡し。例外を共通エラーコードに正規化 |
| **Managers** | 設定、キュー、ログ、進捗、履歴、DL キャッシュ、プロキシ、Cookie |

## コアコンポーネント

- **`ServiceDetector`**: ドメインベースの明示的 URL 判定（`gofile.io` → `gofile` など）
- **`DownloaderFactory`**: エンジンインスタンスの登録と取得
- **`ConfigManager`**: `config.json` の読み込み・マージ・保存
- **`QueueManager`**: ジョブ ID 発行、状態管理、キャンセルフラグ
- **`LogManager`**: 正規化されたログイベント（`[INFO]` 等）
- **`ProgressManager`**: ジョブ単位の進捗スナップショット
- **`HistoryManager`**: 完了ジョブ履歴（`history.json`）
- **`DownloadCacheManager`**: 完了 DL の skip 判定（`download_cache.json`）
- **`RetryManager`**: 設定 `retry` 回数に基づく再試行

## エンジン分離

```text
src/dler_kun/engines/
  twimg/adapter.py
  gofile/
    adapter.py
    douga.py      # gofile-douga JSON API
    lab.py        # gofilelab HTTP
    seeds.py      # ランキングシード解決
  xo85/
    adapter.py
    fast.py       # HTTP 高速クロール
    seeds.py
```

各 adapter は `sys.path` への vendored パス追加、または subprocess（twimg）で既存コードを呼び出します。**vendor 内部の改変は行いません。**

## URL 判定

| ドメイン | エンジン ID |
|----------|-------------|
| `gofile.io` | `gofile` |
| `85xo.com` | `85xo` |
| `tweetfile.com`, `twimg-media.com`, `cdn1.twimg-media.com` | `twimg` |

未対応 URL は `unsupported`（エラーコード `unsupported_service`）を返します。

## ジョブ種別

| kind | 入口 | 説明 |
|------|------|------|
| `download` | `download` コマンド | URL 単位の DL |
| `crawl` | `crawl 85xo` | 85xo 一覧クロール |
| `ranking` | `ranking gofile` / `crawl gofile` | GoFile ランキング URL 収集 |

GoFile の `crawl` は `app.crawl()` 内で `ranking()` に委譲されます（`days` は使用されません）。

## エンジン契約（IDownloader）

```python
detect(url) -> bool
download(request: DownloadRequest) -> DownloadResult
crawl(request: CrawlRequest) -> CrawlResult
ranking(request: CrawlRequest) -> CrawlResult   # GoFile のみ実装
```

未対応機能は `JobStatus.UNSUPPORTED` の `CrawlResult` / `DownloadResult` を返し、CLI へ raw 例外を漏らしません。

**注**: ランキングも `CrawlRequest` / `CrawlResult` を使用します（専用 `RankingResult` 型はありません）。

## リトライ

`config.retry`（既定 2）に基づき、アプリ層で以下のエラーコードを含む失敗のみ再試行します。

| 操作 | 再試行対象エラー |
|------|------------------|
| download | `download_failed`, `network_error` |
| crawl / ranking | `crawl_failed`, `network_error` |

## ランタイムデータファイル

Git 管理外（プロジェクトルート相対）:

| ファイル | 用途 |
|----------|------|
| `config.json` | ユーザー設定 |
| `history.json` | ジョブ履歴 |
| `download_cache.json` | DL 完了キャッシュ |
| `downloads/` | 既定出力先 |
| `logs/` | ログ（エンジン依存） |
| GoFile `tokens.json` 等 | vendored gofile のトークン管理 |

## 出力ディレクトリ規則

- **GoFile download / ranking download**: `output_dir` が既に `gofile` または `rankings` ならそのまま、それ以外は `output_dir/gofile/` 配下へ保存
- **85xo**: `output_dir` をそのまま使用（fast / legacy 共通）
- **twimg**: 指定 `-o` をそのまま使用

## 非交渉ルール

1. vendored downloader の内部ロジックを書き換えない
2. 変更は adapter / wrapper / subprocess 境界に留める
3. 外部プロジェクトパス（`E:\projects\...`）は開発時の一時 override のみ
4. 秘密情報（Cookie、トークン、認証ヘッダ）をログに出さない
