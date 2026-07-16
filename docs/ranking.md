# GoFile ランキング

GoFile ランキング機能は **gofile-douga.com**（JSON API）と **gofilelab.com**（HTML 取得）から `gofile.io/d/...` URL を収集し、任意で GoFile ダウンローダーで保存します。

入口:

- `python -m dler_kun ranking gofile ...`
- `python -m dler_kun crawl gofile ...`（内部で `ranking` に委譲）

## アーキテクチャ

```text
CLI ranking / crawl gofile
  -> DlerKunApp.ranking()
  -> resolve_gofile_ranking_seeds()   # seeds.py
  -> GoFileEngine.ranking()
       ├─ collect_douga_urls()        # douga.py (aiohttp)
       └─ scrape_lab_sources()        # lab.py (aiohttp)
  -> [optional] GoFileDownloader per URL
```

## 既定シード（全 8 ソース）

`config.gofile.ranking_seeds` 未設定時、または `--source` / `--seed` 未指定時に使用:

### gofile-douga（4 ソース）

| キー | シード URL | API エンドポイント |
|------|-----------|-------------------|
| `new` | `https://gofile-douga.com/new` | `GET /api/new?limit=N` |
| `home` | `https://gofile-douga.com/` | `GET /api/rankings?tab=12h&limit=N` |
| `24h` | `https://gofile-douga.com/?sort=24h` | `GET /api/rankings?tab=24h&limit=N` |
| `3days` | `https://gofile-douga.com/?sort=3days` | `GET /api/rankings?tab=3d&limit=N` |

**API 対応の注意点**:

- トップページ（`/`）はフロントエンドも **`tab=12h`（12 時間ランキング）** を既定とする
- `/api/rankings` は **`tab` 必須**（省略すると HTTP 400）
- クエリ `?sort=3days` は API 上 **`tab=3d`** にマップされる

### gofilelab（4 ソース）

| キー | シード URL |
|------|-----------|
| `popular-24h` | `https://gofilelab.com/ja/popular-24h` |
| `popular-30d` | `https://gofilelab.com/ja/popular-30d` |
| `newest` | `https://gofilelab.com/ja/newest` |
| `dl-ranking` | `https://gofilelab.com/ja/dl-ranking` |

年齢確認 Cookie を付けて HTML を取得し、`gofile.io/d/<id>` を正規表現で抽出します（ブラウザ不要）。

---

## `--source` エイリアス

`engines/gofile/seeds.py` の `_SOURCE_ALIASES`:

| エイリアス | 展開先 |
|-----------|--------|
| `douga`, `gofile-douga` | douga 全 4 シード |
| `lab`, `gofilelab` | lab 全 4 シード |
| `new` | `https://gofile-douga.com/new` |
| `home` | `https://gofile-douga.com/` |
| `24h` | douga `?sort=24h` **+** lab `popular-24h` |
| `3days` | `https://gofile-douga.com/?sort=3days` |
| `popular-24h` | lab popular-24h |
| `popular-30d` | lab popular-30d |
| `newest` | lab newest |
| `dl-ranking` | lab dl-ranking |

複数 `--source` は和集合（重複 URL は除去）。

### ソースフィルタリング（douga / lab の ON/OFF）

`--source` 指定時、アプリ層が `douga_enabled` / `lab_enabled` を自動設定:

| 指定例 | douga | lab |
|--------|:-----:|:---:|
| 未指定 | ✓ | ✓ |
| `--source douga` のみ | ✓ | ✗ |
| `--source lab` のみ | ✗ | ✓ |
| douga + lab 混在 | ✓ | ✓ |

---

## シード解決の優先順位

`resolve_gofile_ranking_seeds()`:

1. **`--seed` が HTTP URL** → その URL をそのまま使用
2. **`--seed` が非 HTTP**（例: `24h`）→ エイリアスとして展開
3. **`config.gofile.ranking_seeds`**
4. **`--source` エイリアス展開**
5. **既定 8 シード**

---

## CLI オプション

| オプション | config キー | 既定 | 説明 |
|----------|-------------|------|------|
| `--limit` | `gofile.ranking_limit` | 60 | douga API の `limit`（各ソースキーごと） |
| `--max-more-clicks` | `gofile.max_more_clicks` | 5 | 互換用（現在未使用） |
| `--download` | — | off | 収集後に GoFile DL |
| `-o`, `--output-dir` | `output_dir` | `downloads` | 出力先 |
| `--seed` | — | — | シード URL / エイリアス |
| `--source` | — | 全ソース | ソース絞り込み |

---

## 使用例

```powershell
# 全ソース・収集のみ
python -m dler_kun ranking gofile

# douga 24h のみ、30 件、JSON 出力
python -m dler_kun --json ranking gofile --source 24h --source douga --limit 30

# lab 全ソース、DL 付き
python -m dler_kun ranking gofile --source lab --download -o downloads/gofile

# シード URL 直接指定（douga new のみ）
python -m dler_kun ranking gofile --seed "https://gofile-douga.com/new" --limit 100

# crawl 経由（ranking と同等）
python -m dler_kun crawl gofile --source 3days --download
```

---

## 結果ペイロード

`CrawlResult`（`--json`）:

```json
{
  "job_id": "job-...",
  "engine_id": "gofile",
  "status": "success",
  "message": "GoFile ranking completed: 42 item(s).",
  "items": [
    {
      "url": "https://gofile.io/d/AbCdEf",
      "metadata": { "source": "douga:24h" }
    }
  ],
  "files": [],
  "errors": [],
  "metadata": {
    "download": false,
    "seeds": ["https://gofile-douga.com/?sort=24h"]
  }
}
```

`items[].metadata.source` 形式:

- douga: `douga:new`, `douga:home`, `douga:24h`, `douga:3days`
- lab: `lab:popular-24h`, `lab:newest` 等

---

## 依存関係

| ソース | 必須パッケージ |
|--------|---------------|
| douga | `aiohttp`（本体依存に含む） |
| lab | `aiohttp`（本体依存に含む） |

追加のブラウザ依存はありません。

---

## 重複除去

- douga 内: API レスポンスの `gofileUrl` を dedupe
- lab 内: ページ横断で global dedupe
- 全体: `GoFileEngine.ranking()` が URL セットで最終 dedupe

---

## 出力先

`--download` 時:

- `output_dir` が `gofile` または `rankings` ならその直下
- それ以外は `output_dir/gofile/` 配下

収集のみ（`--download` なし）の場合、ファイルは保存されず `items` のみ返却。
