# Task 4: direct-media engine migration

## Scope and route decision

- Migrated a v2 Videy parser and adapter. Only `videy.co` is registered. Its
  public player page uses `/v?id=<id>`; the current bundle creates a CDN media
  URL from that ID and selects `.mov` for nine-character IDs ending in `2`,
  otherwise `.mp4`.
- Added the Twimg engine contract adapter and a managed subprocess wrapper.
  Verified Twimg-named Fun800 aliases route to `mvfile`, not the legacy Twimg
  tool: identical public bundles on `tweetfile.com`, `twimg-media.com`,
  `cdn1.twimg-media.com`, `video.twimg-image.com`, `media-twimg.com`,
  `cdn.twimg1.com`, `twimg1.com`, `twimg-album.com`, and `twfiles.com` call the
  same Fun800 API and parse the same `netDiskInfo` shape. A live invalid-ID API
  response matched the existing Fun800 parser envelope. This validates host
  ownership and invalid-share handling; a valid-share response remains needed
  to validate these aliases' media/list payloads end to end.
- `twimg.jp`, `video.twimg.jp`, `video.twimg1.com`, `file-bio.com`,
  `gofile.video`, `gofile.trade`, and `video.twimg.news` remain quarantined
  because no matching API/page contract was established. Full sanitized
  observations and bundle hashes are in `tests/fixtures/twimg/ownership-observation.md`.
- The Twimg wrapper captures subprocess output without printing it, supports
  cancellation, discovers only media files, and runs in a temporary directory.
  It publishes only media files to the requested output directory; the vendor's
  SQLite history and captured process output are discarded with staging.
- Both adapters return `DownloadPlan`. The Twimg plan is descriptive because its
  retained vendor resolves and transfers media in one subprocess operation;
  callers use `run_vendor` for that transfer. The existing shared transfer
  service does not yet dispatch vendor-backed plans.
- No v1 source or existing README/AGENTS/docs were edited or removed. The vendor
  file was copied unchanged with its MIT license and provenance note.

## Evidence and fixtures

- Videy public GET: [videy.co](https://videy.co/) and its referenced current
  bundle (`assets/index-Ben4zTgk.js`), inspected 2026-10-16. Sanitized contract
  fixture: `tests/fixtures/videy/player-contract.html` and
  `tests/fixtures/videy/player-contract.js`.
- Twimg-named public GETs and bundles: observations and hashes in
  `tests/fixtures/twimg/ownership-observation.md`; sanitized app shell and API
  invalid-ID fixture in `tests/fixtures/twimg/`.
- Vendored tool provenance and license: `src/dler_kun2/vendor/twimg/PROVENANCE.md`
  and `src/dler_kun2/vendor/twimg/LICENSE`.
- Fixture tests cover current Videy ID/extension handling, invalid IDs, route
  ownership, plan redaction, Twimg quarantine, media discovery, discarded
  database state, missing vendor/runtime, and subprocess cancellation.

## Verification

- `python -m pytest -q` — 174 passed. On this host, run with
  `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` because the auto-loaded Xonsh pytest plugin
  fails before test collection without a Windows console.
- `python -m ruff check src/dler_kun2 tests` — passed.
- `python -m basedpyright` — 0 errors, 0 warnings.
- `python -m dler_kun2 --help` — passed.
- `python -m dler_kun2 detect https://videy.co/v?id=AbCd1234 --json` — reports
  `videy`; `sites --json` reports only the verified `videy.co` host.
