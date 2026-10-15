# Task 4: direct-media engine migration

## Scope and route decision

- Migrated a v2 Videy parser and adapter. Only `videy.co` is registered. Its
  public player page uses `/v?id=<id>`; the current bundle creates a CDN media
  URL from that ID and selects `.mov` for nine-character IDs ending in `2`,
  otherwise `.mp4`.
- Added the Twimg engine contract adapter and a managed subprocess wrapper.
  Twimg aliases remain quarantined: public GETs to `twimg-media.com` and
  `tweetfile.com` returned app shells referencing the same JS bundle, but its
  contents did not expose the API markers or backend identifiers of the
  vendored tool. `cdn1.twimg-media.com` timed out, and `twimg.jp` did not resolve.
  Those observations do not establish ownership or disambiguate Twimg from
  mvfile, so none of these hosts is registered.
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
- Twimg public GETs: `https://twimg-media.com/`,
  `https://tweetfile.com/`, `https://cdn1.twimg-media.com/`, and
  `https://twimg.jp/`, inspected 2026-10-16. Sanitized shell and decision notes:
  `tests/fixtures/twimg/public-app-shell.html` and
  `tests/fixtures/twimg/ownership-observation.md`.
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
