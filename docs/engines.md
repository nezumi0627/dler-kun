# エンジン

各エンジンは `src/dler_kun/engines/<engine_id>/` に adapter を置き、vendored 実装を呼び出します。

## 能力マトリクス

| エンジン | download | crawl | ranking | metadata | login |
|----------|:--------:|:-----:|:-------:|:--------:|:-----:|
| `twimg` | ✓ | — | — | 基本のみ | — |
| `gofile` | ✓ | ✓※ | ✓ | 基本のみ | — |
| `85xo` | ✓ | ✓ | — | 基本のみ | — |
| `mvfile` | ✓ | ✓ | — | 基本のみ | — |

※ GoFile の `crawl` は `ranking` と同一実装（`GoFileEngine.crawl()` → `ranking()`）。

---

## `twimg`

**Vendored**: `src/dler_kun/vendor/twimg/download_twitter_media.py`

### 対応 URL

- `tweetfile.com`
- `twimg-media.com`
- `cdn1.twimg-media.com`

### 統合方式

- 既存 CLI を **subprocess** で実行（SQLite 状態・ログ・依存 bootstrap を維持）
- コマンド: `python download_twitter_media.py <URL> -o <output>`

### CLI オプション（download）

| オプション | 説明 |
|----------|------|
| `--force` | 既存ファイルを上書き |
| `--verbose` | 詳細ログ |
| `--parallel` | 並列数 |
| `--seg-workers` | セグメントワーカー数 |
| `--quality` | 画質指定 |

### 制限

- 独立した crawl / ranking adapter はなし（`JobStatus.UNSUPPORTED`）

---

## `gofile`

**統合**: `src/dler_kun/engines/gofile/gofile_dl/`（旧 `vendor/gofile/gofile_dl` をエンジンに内包）

### 対応 URL

- `gofile.io/d/<id>`

### download

- `GoFileDownloader`（aiohttp）を直接 import して非同期 DL
- プロキシは `config.proxy` 経由
- オプション: `--password`（フォルダパスワード）

### ranking / crawl

ランキング収集は adapter 側の **新規ラッパー**（vendor 改変なし）で 2 ソースを統合:

| モジュール | ソース | 依存 |
|-----------|--------|------|
| `engines/gofile/douga.py` | gofile-douga.com | aiohttp |
| `engines/gofile/lab.py` | gofilelab.com | aiohttp |

収集した `gofile.io/d/...` URL を `CrawlItem` として返し、`--download` 指定時は順次 `GoFileDownloader` で DL します。

詳細: [ranking.md](ranking.md)

### シード解決

`engines/gofile/seeds.py` が以下の優先順位でシード URL を決定:

1. CLI `--seed`（HTTP URL またはエイリアス）
2. `config.gofile.ranking_seeds`
3. CLI `--source` エイリアス展開
4. 全既定シード（douga 4 + lab 4）

### エラー

| 状況 | errors |
|------|--------|
| aiohttp 未インストール | `dependency_missing` |
| douga API 失敗 | `network_error` / `crawl_failed` |
| lab スクレイプ失敗 | `crawl_failed` |
| DL 失敗 | `download_failed` |

---

## `85xo`

**統合**: `src/dler_kun/engines/85xo/xo_dler/`（旧 `vendor/85xo/xo_dler` をエンジンに内包）

### 対応 URL

- `85xo.com` / `www.85xo.com`
- 動画ページ `/v/...`
- 直接メディア URL `/get_file/...mp4`

### download

- 直接メディア URL / 動画ページ URL → fast 経路で即 DL
- それ以外 → 内部で crawl + download 相当

### crawl: `fast`（既定）

`engines/85xo/fast.py`:

1. シード一覧ページを HTTP で走査（`max_pages` まで）
2. 一覧の日付テキストで `--days` 以内に絞り込み
3. 動画ページ HTML から `get_file` URL を解決し最高 `br` mp4 を選択
4. vendored `download_items` / 並列 curl 保存

| オプション | 既定 | 説明 |
|----------|------|------|
| `--days` | 10 | 遡及日数 |
| `--max-pages` | 50 | シードあたり最大ページ |
| `--resolve-workers` | 6 | URL 解決並列数 |
| `--parallel-downloads` | 4 | DL 並列数 |
| `--download-read-timeout` | 30 | 転送停滞打ち切り秒（1 KiB/s 未満） |
| `--download-attempts` | 2 | リトライ回数 |
| `--download-max-time` | — | curl 全体上限秒（任意） |
| `--include-undated` | off | 日付不明項目を含める |
| `--overwrite` | off | 既存ファイルを上書き |

### crawl: `legacy`

vendored `xo_dler.crawl_once(CrawlConfig(...))`:

- headless Chrome でネットワークキャプチャ
- `Last-Modified` ベースの日付判定（日付不明は `--include-undated` まで除外）
- `--network-capture-seconds`, `--browser-path`, `--delay-seconds`, `--max-depth` 等

```powershell
python -m dler_kun crawl 85xo --method legacy --days 10 --download
```

### 既定シード

```text
https://www.85xo.com/ja/latest-updates/
https://www.85xo.com/vi/latest-updates/
```

`--seed` または `config.85xo.default_seeds` で上書き可能。

### 制限

- `fast`: 一覧日付テキストと動画ページ `uploadDate` / `get_file` HTML に依存
- `legacy`: Chrome / Selenium 系依存、低速

---

## `mvfile`

**実装**: `src/dler_kun/engines/mvfile/`（公開 land-page API + HLS）

### 対応 URL

- `mvfile.com` / `cdn.mvfile.com` / `*.mvfile.com`
- 共有ショートリンク `https://cdn.mvfile.com/<id>`

### download

1. `/flow/land-page/getInfo` で単体 / フォルダを判定
2. フォルダなら `/flow/land-page/list_by_links_page` で子を列挙し各 `getInfo` でメディア URL を解決
3. HLS（`playlist.m3u8`）を `curl`（DoH 解決 IP 付き）で取得し、`ffmpeg -c copy` で mp4 化

依存: システム `curl` と `ffmpeg`

### crawl

- `--seed` に共有 URL を指定
- フォルダなら一覧、単体なら 1 件を `CrawlItem` として返す
- `--download` で続けて保存

```powershell
dler-kun detect https://cdn.mvfile.com/3EN1gA
dler-kun download https://cdn.mvfile.com/3EN1gA -o downloads/mvfile
dler-kun crawl mvfile --seed https://cdn.mvfile.com/cv9NBN --download -o downloads/mvfile
```

### 設定 (`config.mvfile`)

| キー | 既定 | 説明 |
|------|------|------|
| `api_base` | `https://rwzugqnp.fun800.click/app-api` | land-page API 基点 |
| `timeout_seconds` | `30` | API / セグメント取得タイムアウト |

### 制限

- ranking 非対応
- パスワード保護ページは `auth_required`
- 動画 CDN の DNS 汚染対策として DoH + `curl --resolve` を使用

---

## コード所有

- gofile エンジン: `engines/gofile/gofile_dl/`（旧 `vendor/gofile/gofile_dl` を統合）
- 85xo エンジン: `engines/85xo/xo_dler/`（旧 `vendor/85xo/xo_dler` を統合）
- twimg: `vendor/twimg/download_twitter_media.py` のみ vendored（subprocess 呼び出し）

外部プロジェクトへのランタイム依存はありません。`config.engine_paths` は twimg のみ。
