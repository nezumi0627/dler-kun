# GoFile Ranking/Crawl バグレポート

**日付:** 2026-07-16  
**対象:** GoFile ranking/crawl 統合 (`adapter.py`, `douga.py`, `lab.py`, `seeds.py`, `app.py`, `__main__.py`)  
**検証:** ユニットテスト 64 件 OK（`PYTHONPATH=src`）、`ranking gofile --source douga --limit 1` で limit 挙動を実地確認

## サマリー（深刻度別）

| 深刻度 | 件数 |
|--------|------|
| 高     | 3    |
| 中     | 5    |
| 低     | 2    |
| **合計** | **10** |

---

## 所見一覧

### 1. [高] douga-only 指定時に lab が全ページスクレイプされる

- **場所:** `src/dler_kun/engines/gofile/adapter.py:347-351`, `src/dler_kun/engines/gofile/lab.py:173-179`
- **説明:** `_lab_seeds_from_resolved()` は resolved が douga のみのとき空リスト `[]` を返す。しかし `scrape_lab_sources([])` は Python 上 falsy と判定され、`sources is None` と同じく **全 LAB ページ**（popular-24h / 30d / newest / dl-ranking）をスクレイプする。`--source douga` でも `lab_enabled=True` のまま（後述 #3）だと、意図せず Playwright が全 lab ページを起動する。
- **再現:** `--source douga` + デフォルト flags → `_lab_seeds_from_resolved` が `[]` → lab 全件スクレイプ。
- **修正案:** `scrape_lab_sources` で `sources is not None and len(sources)==0` を「スクレイプなし」と扱う。または `_lab_seeds_from_resolved` が douga-only のとき `None` ではなく明示的な sentinels を返し、adapter 側で lab ブロックをスキップする。

---

### 2. [高] lab-only シードでも douga がデフォルト全ソースにフォールバック

- **場所:** `src/dler_kun/engines/gofile/adapter.py:301-305`, `src/dler_kun/app.py:446-465`
- **説明:** `collect_douga_urls()` は resolved に douga シードが無い場合、**常に** `_DOUGA_SEEDS` 全 4 ソースへフォールバックする。`_gofile_source_flags()` は `--source` 未指定時 `douga_enabled=True` を返すため、`--seed https://gofilelab.com/ja/newest` のように lab URL のみ指定しても douga 4 ソースが取得される（実地確認: lab-only seeds で douga キー 4 件が呼ばれる）。
- **修正案:** フォールバックは `douga_enabled` かつ resolved に douga 系が含まれない **かつ** ユーザーが明示的に全ソースを選んだ場合に限定。lab-only / `--source lab` では douga ブロック自体をスキップ。

---

### 3. [高] `--source` 未指定時、resolved シードから douga/lab フラグを推論しない

- **場所:** `src/dler_kun/app.py:446-465`
- **説明:** `_gofile_source_flags()` は `options["sources"]` のみ参照し、`request.seeds` / resolved URL は見ない。`--seed lab` や lab URL のみ指定でも `douga_enabled=True, lab_enabled=True` となり、#2 の douga フォールバックと組み合わさって **lab 指定なのに douga も走る**。
- **再現:** `resolve_gofile_ranking_seeds(['lab'])` + `_gofile_source_flags(..., None)` → 両方 True。
- **修正案:** `sources` 未指定時は resolved seeds を `classify_ranking_seed()` で分類し、片方のみならもう片方を `False` にする。

---

### 4. [中] `crawl gofile` が orphan キュージョブを残す

- **場所:** `src/dler_kun/app.py:159`, `177-184`
- **説明:** `crawl()` は先に `kind=crawl` のキュージョブを作成した後、`gofile` だけ `ranking()` に委譲する。`ranking()` は別途 `kind=ranking` ジョブを作成するため、crawl ジョブは **PENDING のまま放置**される（実地確認: crawl gofile 後に pending crawl ジョブが 1 件残存）。
- **修正案:** gofile の場合は crawl ジョブを作らず最初から `ranking()` を呼ぶ。または委譲前に crawl ジョブをキャンセル/再利用する。

---

### 5. [中] `limit` がソース全体ではなく douga ソースキーごとに適用される

- **場所:** `src/dler_kun/engines/gofile/adapter.py:138`, `309-310`
- **説明:** `limit` は `collect_douga_urls()` 内の各 source key へ個別に渡される。`--source douga --limit 1` で **4 item** が返る（4 ソース × limit 1）。CLI/設定の `ranking_limit` の意味とユーザー期待がずれる。
- **再現:** `python -m dler_kun ranking gofile --source douga --limit 1` → `4 item(s)`。
- **修正案:** グローバル limit を跨ソースで共有し、上限に達したらループ打ち切り。または limit を「ソースあたり」とドキュメント/CLI ヘルプで明示。

---

### 6. [中] 部分的成功が SUCCESS 扱いになりリトライ・終了コードが効かない

- **場所:** `src/dler_kun/engines/gofile/adapter.py:179-184`, `221-230`, `257-265`; `src/dler_kun/app.py:408-421`
- **説明:** douga が `DougaFetchError` で `network_error` を記録しても lab が成功すれば `items` があり `status=SUCCESS` になる。`_run_ranking_with_retry()` は `FAILED` のみリトライするため **network_error が残っても再試行されない**。CLI も exit 0 になる。
- **修正案:** ソース単位の失敗がある場合は `PARTIAL` 相当のステータスにするか、`errors` に retryable コードがあれば `FAILED` とする。

---

### 7. [中] douga の `ModuleNotFoundError` で lab クロール全体が中断

- **場所:** `src/dler_kun/engines/gofile/adapter.py:171-178`
- **説明:** aiohttp 欠如時、douga ブロックの `ModuleNotFoundError` で **即 return** し `lab_enabled=True` でも lab が実行されない。lab は Playwright のみで動作可能なのに dependency_missing で全体失敗になる。
- **修正案:** `dependency_missing` を errors に追加して douga ブロックのみスキップし、lab ブロックへ続行。両方不可のときだけ return。

---

### 8. [中] ranking ダウンロードループ中にキャンセル不可

- **場所:** `src/dler_kun/engines/gofile/adapter.py:234-251`; `src/dler_kun/app.py:293-296`
- **説明:** `app.ranking()` のキャンセルチェックは ranking 呼び出しの前後のみ。`request.download=True` 時、adapter は全 item を逐次 `_download_async()` するが、`progress_callback` も `_raise_if_cancelled` も呼ばれない。大量 item では `cancel` が効かない。
- **修正案:** ダウンロード各イテレーションで `request.options.get("progress_callback")` 経由または専用 callback で `JobCancelled` を確認する（85xo fast と同様）。

---

### 9. [低] 非 HTTP エイリアスシードが app 層で未展開のまま渡る

- **場所:** `src/dler_kun/engines/gofile/seeds.py:87-90`; `src/dler_kun/app.py:264-270`
- **説明:** `resolve_gofile_ranking_seeds(seeds=['lab'])` は `['lab']` をそのまま返す（エイリアス未展開）。adapter の `_resolve_ranking_seeds()` は非 HTTP シードを検知して再展開するため **二重解決で結果は一致しうる**が、app 層の `_gofile_source_flags(resolved, ...)` は未展開の `['lab']` を見て #3 の誤フラグになる。CLI `--seed lab` と `--source lab` で挙動が不一致。
- **修正案:** app 層でも非 HTTP シードは `expand_source_aliases()` するか、フラグ判定を adapter と同じロジックに統一。

---

### 10. [低] テストが統合バグを見逃す（過剰モック）

- **場所:** `tests/test_gofile_lab.py:191-234`
- **説明:** `GoFileRankingAdapterTests` は `fetch_douga_urls` をモックし `seeds=['lab']` で成功を確認するが、#2/#3 により **lab 指定でも douga が呼ばれる** 実挙動を検証していない。モックが douga 呼び出しを成功させるため、ソース分離バグが隠れる。
- **修正案:** `collect_douga_urls` / `_gofile_source_flags` / `_lab_seeds_from_resolved` のユニットテストを追加し、lab-only / douga-only で反対ソースが呼ばれないことを assert する。

---

## 参考（深刻度低・共有コード）

- **`asyncio.run` 二重起動リスク:** `download()` / `ranking()` は各 `asyncio.run()` を使用（`adapter.py:58,116`）。ranking 内ダウンロードは `await _download_async` で同一ループ内のため nested run ではないが、既存 event loop 上（例: Jupyter / 非同期 CLI）から呼ぶと `RuntimeError` になる可能性あり。現状 CLI 同期呼び出しでは問題なし。
- **twimg / 85xo:** 共有 `app.py` の ranking 経路変更による回帰は確認されず。85xo crawl の retry/cancel パスは従来通り。

## 修正実施

**2026-07-16 対応済み（全10件）:**

| # | 修正内容 |
|---|----------|
| 1 | `lab.scrape_lab_sources([])` は空結果を返し Playwright を起動しない。douga-only 時は adapter が lab をスキップ |
| 2 | `collect_douga_urls` は seeds に douga が無い場合フォールバックしない |
| 3 | `_gofile_source_flags` / `_infer_source_flags` が resolved seeds から douga/lab を推論 |
| 4 | `crawl gofile` はキュー作成前に `ranking()` へ委譲 |
| 5 | `limit` をソース横断のグローバル上限として適用 |
| 6 | 収集エラー（network/crawl/dependency）がある場合は `FAILED`（リトライ対象） |
| 7 | aiohttp 欠如時は douga のみスキップし lab を継続 |
| 8 | ダウンロード各件で `progress_callback` を呼びキャンセル可能に。`JobCancelled` は再送出 |
| 9 | `resolve_gofile_ranking_seeds` が `lab` 等のエイリアスを展開 |
| 10 | lab-only / douga-only / limit / flags の回帰テストを追加 |

本調査時点ではプロダクション変更なしだったが、上記のとおり修正済み。
