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

## コマンド一覧

| コマンド | 説明 |
|----------|------|
| `detect <url>` | URL がどのエンジンで処理できるか判定 |
| `download <urls...>` | 1 件以上の URL をダウンロード |
| `crawl <service>` | エンジンをクロール（`85xo` / `gofile` / `mvfile`） |
| `ranking <service>` | ランキングクロール（`gofile` のみ） |
| `cancel [job_id]` | 実行中ジョブをキャンセル |
| `config` | 有効設定を JSON 表示 |

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
| `--verbose` | twimg 詳細ログ |
| `--parallel` | twimg 並列数 |
| `--seg-workers` | twimg セグメントワーカー |
| `--quality` | twimg 画質 |
| `--password` | GoFile フォルダパスワード |

複数 URL は順次処理。各 URL は個別に detector → engine download されます。

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
| `--resolve-workers` | 6 | fast: URL 解決並列 |
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
# 85xo 高速クロール + DL
python -m dler_kun crawl 85xo --days 10 --download --method fast -o downloads/85xo

# GoFile（ranking と同等）
python -m dler_kun crawl gofile --source douga --download
```

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
