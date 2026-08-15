# CLI リファレンス

```powershell
python -m dler_kun [--json] <command> [options]
# または
dler-kun [--json] <command> [options]
```

## グローバルオプション

| オプション | 説明 |
|----------|------|
| `--json` | 人間向けサマリーの代わりに機械可読 JSON を stdout に出力 |

実行中の `crawl` / `download` / `ranking` は **Ctrl+C** で安全に停止できます。進行中の転送は打ち切られ、途中データは再開用に残ります。mvfile / gofilerun は取得済み HLS セグメントを `.hlsd` ステージングに保存するため、再実行時に途中から再開します（完了済みファイルはスキップ）。終了コードは 130。

85xo の fast クロールは動画 URL 解決の結果を `fast_capture_cache.json`（プロジェクト直下、TTL 30日）にキャッシュします。同じ動画ページを再解決しないため再クロールが高速化します。削除すれば再取得します。

## コマンド一覧

| コマンド | 説明 |
|----------|------|
| `detect <url>` | URL がどのエンジンで処理できるか判定 |
| `download <urls...>` | 1 件以上の URL をダウンロード |
| `crawl <service>` | エンジンをクロール（`85xo` / `gofile` / `mvfile` / `mixixxx`） |
| `ranking <service>` | ランキングクロール（`gofile` のみ） |
| `cancel [job_id]` | 実行中ジョブをキャンセル |
| `config` | 有効設定を JSON 表示 |
| `help` | 全コマンド・オプションの usage を表示 |

### 共通オプション（download / crawl / ranking で使用可）

| オプション | 説明 |
|----------|------|
| `--local-addr IP` | ソース IP バインド（例: iPhone USB テザリング `172.20.10.2`）。config `local_addr` を上書き。※ mixixxx のみ非対応（Chrome が通信を所有） |
| `--proxy URL` | HTTP/SOCKS プロキシ（config `proxy` を上書き） |
| `--user-agent UA` | User-Agent 上書き |
| `--cookie VALUE` | Cookie ヘッダ上書き |
| `--api-base URL` | mvfile / gofilerun: API ベース URL 上書き |
| `--timeout SEC` | ネットワークタイムアウト秒 |

---

## `detect`

```powershell
python -m dler_kun detect https://gofile.io/d/example
# [SUCCESS] gofile

python -m dler_kun --json detect https://example.com/unknown
# {"url": "...", "engine_id": null, "supported": false, "message": "対応サービスではありません"}
```

**終了コード**: 対応 → 0、未対応 → 1

---

## `download`

```powershell
python -m dler_kun download URL [URL ...] [-o OUTPUT_DIR] [options]
```

| オプション | 説明 |
|----------|------|
| `-o`, `--output-dir` | 出力先（既定: `config.output_dir` → `downloads`） |
| `--force` | 既存ファイルを上書き（twimg / 85xo 直接 DL） |
| `--metadata` | `<file>.json` メタデータサイドカーを書き出す（既定: オフ） |
| `--verbose` | twimg 詳細ログ |
| `--parallel` | twimg 並列数 |
| `--seg-workers` | twimg セグメントワーカー |
| `--quality` | twimg 画質 |
| `--password` | GoFile フォルダパスワード |
| `--single` | mvfile: 対象の1ファイルのみ DL（既定: チャンネルの関連リスト全件） |
| `--hls-workers` | 8 | mvfile: 並列 HLS セグメント取得数 |
| `--parallel-urls` | 自動（最大4） | URL 単位の並列 DL。1 で順次 |
| `--segment-concurrency` | 4 | mixixxx: 同時 HLS セグメント取得数 |

複数 URL は順次処理。各 URL は個別に detector → engine download されます。

`download` は URL 末尾の ID（例 `https://gofile.website/ZLk4B5` → `ZLk4B5`）をフォルダ名にして `-o` 配下に保存します。`crawl` は指定フォルダ直下にまとめて保存します。

**終了コード**: 全件成功 → 0、1 件でも失敗 → 1

---

## `crawl`

```powershell
python -m dler_kun crawl {85xo|gofile} [options]
```

### 共通オプション

| オプション | 説明 |
|----------|------|
| `--seed` | シード URL（複数指定可、`action=append`） |
| `-o`, `--output-dir` | 出力先 |
| `--download` | 収集したメディアをダウンロード |

### 85xo 専用

| オプション | 既定 | 説明 |
|----------|------|------|
| `--days` | 10 | 遡及日数 |
| `--method` | `fast` | `fast` または `legacy` |
| `--max-pages` | 50 | 最大一覧ページ数 |
| `--max-depth` | 2 | legacy: クロール深度 |
| `--delay-seconds` | 1.0 | legacy: ページ間待機 |
| `--network-capture-seconds` | 15.0 | legacy: ネットワークキャプチャ秒 |
| `--browser-path` | — | legacy: Chrome パス |
| `--include-undated` | off | 日付不明を含める |
| `--overwrite` | off | 既存を上書き |
| `--metadata` | off | `<file>.json` メタデータサイドカーを書き出す |
| `--resolve-workers` | 6 | fast: URL 解決並列 |
| `--discover-workers` | 6 | fast: 一覧ページ取得並列 |
| `--parallel-downloads` | 4 | fast: DL 並列 |
| `--download-read-timeout` | 30 | fast: 停滞打ち切り秒 |
| `--download-attempts` | 2 | fast: DL リトライ |
| `--download-max-time` | — | fast: curl 上限秒 |

### GoFile（`crawl gofile` = ranking 委譲）

`ranking gofile` と同じオプションが使えます:

| オプション | 既定 | 説明 |
|----------|------|------|
| `--source` | 全ソース | ランキングソースエイリアス（複数可） |
| `--limit` | 60 | douga API の `limit` |
| `--max-more-clicks` | 5 | 互換用（現在未使用） |

```powershell
# 85xo 高速クロール + DL（最新15日分）
python -m dler_kun crawl 85xo --days 15 --download --discover-workers 12 --resolve-workers 12 --parallel-downloads 8 -o downloads/85xo

# GoFile（ranking と同等）
python -m dler_kun crawl gofile --source douga --download
```

### mixixxx（`crawl mixixxx`）

LuluStream 埋め込みの署名付き HLS を **Chrome（ヘッドレス）経由で取得** し、ffmpeg で mp4 結合します。CDN が実ブラウザの TLS フィンガープリントを検証するため、ブラウザは必須です。

2 段階の並列化で高速化できます:

| オプション | 既定 | 説明 |
|----------|------|------|
| `--parallel-downloads` | 3 | 同時に動かすブラウザセッション数（動画単位の並列） |
| `--segment-concurrency` | 4 | 1 セッション内の同時 HLS セグメント取得数（動画内の並列） |

```powershell
# 全ページ取得（例: 69ページ分、-o で出力先）
python -m dler_kun crawl mixixxx --max-pages 69 --download --parallel-downloads 3 --segment-concurrency 8 -o mixi-xxx
```

- 要 Chrome/Edge + ffmpeg（PATH に存在すれば自動検出）
- 一覧ページは `{seed}/page/N/` の形式を想定（既定シード: `https://mixi-xxx.cc/`）
- 既存 mp4 はスキップ（再開・重複回避）
- 実測: セグメント並列取得で 1 本あたり 166s → 110s（約 1.5 倍）

`--discover-workers` は一覧ページ取得を並列化するため、`--days` が大きいクロールほど効果が出ます（`--method fast` のみ）。

---

## `ranking`

```powershell
python -m dler_kun ranking gofile [options]
```

GoFile ランキング専用コマンド。`crawl gofile` と同じ `app.ranking()` を呼びます。

| オプション | 既定 | 説明 |
|----------|------|------|
| `--seed` | — | シード URL またはエイリアス（複数可） |
| `--source` | 全ソース | `douga`, `lab`, `24h`, `new` 等（複数可） |
| `--limit` | 60 | douga API limit |
| `--max-more-clicks` | 5 | 互換用（現在未使用） |
| `-o`, `--output-dir` | `downloads` | 出力先 |
| `--download` | off | 収集 URL を GoFile DL |

```powershell
# 全ソース収集のみ
python -m dler_kun ranking gofile --json

# lab の newest のみ、DL 付き
python -m dler_kun ranking gofile --source newest --source lab --download
```

詳細: [ranking.md](ranking.md)

---

## `cancel`

```powershell
python -m dler_kun cancel JOB_ID
python -m dler_kun cancel --all
```

実行中ジョブにキャンセルフラグを立て、次のチェックポイントで `JobCancelled` として終了します。

**終了コード**: 成功 → 0、`unsupported`（ジョブ未発見） → 1

---

## `config`

```powershell
python -m dler_kun config              # マージ後設定を JSON 表示（常に JSON）
python -m dler_kun config --save       # 既定 config.json を書き出し
```

`--json` フラグは `config` コマンドでは常に JSON 出力のため実質不要です。

---

## 出力形式

### 人間向け（既定）

```
[SUCCESS] gofile
[ERROR] 対応サービスではありません
[INFO] gofile: GoFile ranking completed: 42 item(s).
  items: 42
  files: 10
```

タグ: `[INFO]`, `[DEBUG]`, `[WARNING]`, `[ERROR]`, `[SUCCESS]`

### JSON（`--json`）

`DownloadResult`, `CrawlResult`, 検出結果など dataclass を JSON 化した完全ペイロード。

---

## 終了コードまとめ

| 状況 | コード |
|------|--------|
| 成功 / キャンセル完了 | 0 |
| 失敗 / 未対応 detect | 1 |
| 引数エラー（help） | 2 |
