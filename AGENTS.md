# AGENTS.md

## Project Mission

`dler-kun` integrates downloader engines behind one detector, queue, CLI, and configuration surface.

## Code Ownership

Downloader code migrated from the author's earlier tools is **integrated in-tree** and owned by this project:

- `src/dler_kun/engines/gofile/gofile_dl/` — GoFile downloader (migrated from the author's earlier tool)
- `src/dler_kun/engines/85xo/xo_dler/` — 85xo crawler/downloader (migrated from the author's earlier tool)

Only `src/dler_kun/vendor/twimg/download_twitter_media.py` remains vendored (invoked as a subprocess). Treat it as an external tool: prefer wrapper-side changes over editing it.

## Architecture Rules

- CLI calls application services only.
- `ServiceDetector` owns URL/service detection.
- **Never route by domain name alone.** Similarly named services can be completely different backends: `gofile.rocks` / `gofile.website` / `gofile.run` are vll/fun800 netdisks (mvfile engine), not gofile.io mirrors; `tweetfile.com` / `tweetplay.com` / `image-share.cc` / `imagedist.com` are also vll. When adding a new domain, verify the actual backend (SPA framework, API host, response shape) before choosing the engine.
- `DownloaderFactory` owns engine lookup and registration.
- Each engine implements `IDownloader`.
- Managers own shared concerns: config, queue, logging, progress, history, retry, proxy, cookies.
- Engine modules stay isolated under `src/dler_kun/engines/<engine_id>/`.
- `src/dler_kun/net.py` is the shared curl wrapper (headers, `--interface` binding, DoH resolve, stall detection, proxy). New curl-based downloads should use it instead of building subprocess commands.
- The `engines/85xo/` package name starts with a digit, so it cannot be imported with normal syntax. Cross-package imports (e.g. mixixxx → `network_media`) go through `importlib.import_module("dler_kun.engines.85xo.xo_dler.network_media")`, matching the existing `engine_85xo.py` pattern.

## Engine Contract

Each engine should expose these capabilities when supported:

- `detect(url) -> bool`
- `download(request) -> DownloadResult`
- `crawl(request) -> CrawlResult`
- `ranking(request) -> CrawlResult`（GoFile のみ。専用 RankingResult 型はない）
- `get_metadata(url) -> Metadata`
- `login(settings) -> LoginResult`

Unsupported features must return a common unsupported result, not raise raw implementation-specific exceptions to the CLI.

## Error Handling

Catch engine-specific exceptions at the engine adapter boundary and return common errors:

- `unsupported_service`
- `invalid_request`
- `not_found`
- `auth_required`
- `network_error`
- `download_failed`
- `crawl_failed`
- `dependency_missing`

`src/dler_kun/net.py` raises `CurlDownloadError` / `CurlCancelled`; adapters map these to the common codes above.

## Logging

Use these levels in user-visible logs:

- `[INFO]`
- `[DEBUG]`
- `[WARNING]`
- `[ERROR]`
- `[SUCCESS]`

Never log secrets, cookies, GoFile tokens, or raw authorization headers.

## Quality

Minimum verification before commit:

```powershell
python -m ruff check src/dler_kun
python -m basedpyright
python -m dler_kun --help
```

Style is enforced by ruff (`pyproject.toml`); type checking by basedpyright.
Keep modules import-light: heavy third-party imports stay inside functions
(e.g. `requests`, browser/CDP helpers) so `import dler_kun` stays fast.

CLI defaults to a short human summary. Use `--json` when a full payload is needed.
When validating existing projects, prefer their public CLI/API and do not modify their code.

## Related-media download playbook (mvfile / vll / fun800)

The following sites are not GoFile.io mirrors.  They use the mvfile/fun800 land-page
backend and an entry URL may point to one media item inside a related collection:

- `gofile.bar` uses `https://gofile.bar/api.php?endpoint=/flow/...`.
- `image-share.cc` and similar `tweetfile.com` / `tweetplay.com` / `imagedist.com`
  domains use the vll/fun800 API family.

Before downloading one of these URLs:

1. Detect it as `mvfile`; never treat a non-folder root as proof that the URL is a
   single-file collection.  Resolve `related=True` and inspect the discovered target
   count first.  The related list can be paginated and can change between runs.
2. For `gofile.bar`, parse list entries from `data.list[*].netDiskInfo`, and use the
   root `extraInfo.externalLinks` channel when the root itself is a member of that
   channel.  The `getInfo` response and the list response have different nesting.
3. Validate every target's `media_url`.  Values ending in `/null` are unavailable
   source records, not downloadable files; report them separately instead of claiming
   the collection is complete.
4. Signed object-store URLs ending in `.mp4`, `.mov`, `.m4v`, `.webm`, or `.mkv` are
   direct media downloads.  Do not feed them into the HLS playlist parser; binary
   content can produce Windows `embedded null character` failures.
5. Collection members can share the same display name.  Include the short link in
   the local filename for duplicate names so one item cannot overwrite another.
6. Run the public CLI with `--god` and a dedicated output directory, then compare the
   discovered target count with the completed, non-temporary output files.  Keep HLS
   staging files out of that count.  A success line from the CLI is not enough if
   some targets were `/null` or if duplicate names collapsed onto one path.

Typical workflow:

```powershell
python -m dler_kun detect https://gofile.bar/d/cs5AeP
python -m dler_kun download https://gofile.bar/d/cs5AeP --god -o downloads/gofile-bar-cs5AeP-all
python -m dler_kun download https://cdn2.image-share.cc/k3KlOo --god -o downloads/image-share-k3KlOo-all
```

When reporting completion, include: discovered target count, successful output count,
unavailable `/null` count, and the output directory.  Never expose signed media URLs,
cookies, or authorization headers in logs or reports.
