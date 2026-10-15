# dler-kun Modernization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` or `subagent-driven-development` to implement this plan task-by-task. Checkboxes track each task.

**Goal:** 修正済みURL検出と衝突しない保存先、有限時間で停止するネットワーク、正しい失敗分類を全エンジンで揃え、計測で確認できる性能改善を行う。

**Architecture:** CLI/application/factory/engine境界を維持し、共通の安全性問題はapp、queue、shared networkで一度だけ直す。サービス固有の解析とHTTPエラーは各engine adapterに置き、サイト公開仕様をfixture化して互換性を継続検証する。

**Tech Stack:** Python 3.10+, stdlib, aiohttp, pytest, ruff, basedpyright; 追加依存なし。

**Spec:** `docs/superpowers/specs/2026-10-15-dler-kun-modernization-design.md`

## Global Constraints

- Preserve the pre-existing changes in `detector.py`, `engines/mvfile/adapter.py`, and `engines/mvfile/api.py`.
- Do not route a service by domain name alone when the backend is ambiguous.
- Use `src/dler_kun/net.py` for new curl downloads.
- Never log secrets, cookies, GoFile tokens, signed URLs, or authorization headers.
- Do not bypass rate limits or access controls; honor `Retry-After`, apply bounded retry, then stop.
- Do not add dependencies without a measured need.

## Review Focus

- Different URLs sharing a basename/host/path, including query-only differences, never write into the same URL output directory; exact duplicate inputs are not downloaded concurrently.
- Cancel racing with success/failure leaves one terminal status and never overwrites cancellation.
- Timeouts and rate-limit waits do not become unbounded or retry earlier than the server requests.
- Partial HLS/page failures never produce a false success or a malformed concatenation list.
- Unsupported and dependency errors remain actionable and preserve safe output paths.

---

### Task 1: Collision-safe URL output allocation

**Files:** `src/dler_kun/app.py`, possibly `src/dler_kun/pathing.py`; create `tests/test_app_output_paths.py`.

**Interfaces:** Keep `DlerKunApp.download_urls()` public signature unchanged. Introduce a private URL identity allocator that receives the full URL, derives a filesystem-safe stable identity from the canonical URL (including query), and returns an output directory ID. Pre-allocate IDs before parallel workers start; ensure unique IDs within the batch and collapse exact duplicate inputs into one download while preserving the caller's result order. A new ID must not overwrite a pre-existing legacy directory.

- [ ] Write regression tests for same basename across hosts, same host/path with different query, repeated exact URLs under parallel execution, case-insensitive Windows path collisions, invalid/reserved characters, and legacy output directory preservation.
- [ ] Run `pytest tests/test_app_output_paths.py -q`; confirm each new case fails before implementation.
- [ ] Implement deterministic host/slug plus SHA-256 of the full normalized URL, batch-level collision detection, duplicate coalescing, and safe reservation of output directories. Do not put query strings or signed tokens in names/logs.
- [ ] Run focused tests and `pytest tests/test_app_output_paths.py -q` again.

### Task 2: Shared timeout and atomic job completion

**Files:** `src/dler_kun/net.py`, `src/dler_kun/managers.py`, `src/dler_kun/app.py`; create focused network/queue tests.

**Interfaces:** Add an atomic queue completion method that checks cancellation and writes the terminal result under one lock. Preserve existing manager calls where possible. `fetch_text(timeout_seconds=...)` must enforce that wall-clock limit and map expiration to `CurlDownloadError`.

- [ ] Add tests proving `fetch_text` times out and cancellation cannot be overwritten by completion.
- [ ] Observe expected failures.
- [ ] Implement subprocess timeout/cleanup and the atomic terminal-state transition.
- [ ] Run focused tests and the app/network/queue test files.

### Task 3: Request validation and zero-day semantics

**Files:** `src/dler_kun/app.py`, relevant `85xo` adapter; create/update crawl request tests.

- [ ] Add tests for explicit `days=0`, omitted days, negative days, and invalid parallel counts.
- [ ] Preserve `0`; reject invalid negative values at the application boundary using the common error contract.
- [ ] Run focused tests before and after the implementation.

### Task 4: Engine result correctness

**Files:** `src/dler_kun/engines/mixixxx/fast.py`, `mixixxx/adapter.py`, `85xo/fast.py`, `twimg/adapter.py`, `linkex/adapter.py`; matching engine tests.

- [ ] Add tests for sparse HLS segment success, zero successful downloads, one failed page in a concurrent crawl, missing ffmpeg, Twimg file reporting, and invalid Linkex input classification.
- [ ] Implement only the owning-layer corrections; preserve remaining crawl results and report partial failures accurately.
- [ ] Run the affected engine test modules.

### Task 5: GoFile rate-limit and HTTP lifecycle

**Files:** `src/dler_kun/engines/gofile/gofile_dl/downloader/go_file_api.py`, GoFile adapter and token/API tests.

- [ ] Add tests for numeric and HTTP-date `Retry-After`, 429 JSON envelope, delays beyond the local automatic-wait ceiling, response release on retry, and normalized error codes.
- [ ] Respect valid server delay. When the delay exceeds the configured automatic-wait ceiling, stop and return rate-limit information rather than retrying early. Never rotate IP/account/token to evade a limit.
- [ ] Release each retryable response and distinguish rate-limit, auth, not-found, network, and missing-dependency errors at the adapter boundary.
- [ ] Resolve existing basedpyright errors in this package without suppressing diagnostics.
- [ ] Run focused GoFile tests.

### Task 6: Current public-site compatibility

**Files:** affected engine modules and fixtures under `tests/fixtures` (create only where needed).

- [ ] For each reachable supported site, record page/script provenance and fetch date without storing cookies, tokens, signed links, or personal content.
- [ ] Compare current route, API envelope, pagination, and direct-media/HLS response against the owning adapter.
- [ ] Add sanitized fixtures for confirmed public response shapes; update parsers only where they no longer match.
- [ ] Report unreachable sites as unverified instead of claiming compatibility.

### Task 7: Full gates and measured performance

**Files:** only modules and minimal benchmark helper required by measured bottlenecks.

- [ ] Run the complete pytest suite, `ruff check src/dler_kun`, `basedpyright`, and `python -m dler_kun --help`.
- [ ] Measure representative local/mock workloads before and after any concurrency or buffering change; do not benchmark remote services with burst traffic.
- [ ] Fix all regressions and record remaining unverified sites and environment-dependent performance limits.
- [ ] Review the full diff, including the three pre-existing edits, and verify they remain intact.
