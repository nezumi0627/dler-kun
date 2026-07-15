# AGENTS.md

## Project Mission

`dler-kun` integrates mature downloader projects behind one detector, queue, CLI, and configuration surface.

## Non-Negotiable Rule

Do not rewrite existing downloader internals.

The original local projects are source references only:

- twimg downloader source
- `E:\projects\gofile-downloader`
- `E:\projects\85-xo`

Runtime code must use the vendored copies under `src/dler_kun/vendor/` by default. External paths are only for temporary development overrides.

Use Adapter, Facade, Wrapper, or subprocess boundaries inside `dler-kun`. If a change appears necessary in vendored engine logic, document the reason first and prefer a wrapper-side workaround.

## Architecture Rules

- CLI calls application services only.
- `ServiceDetector` owns URL/service detection.
- `DownloaderFactory` owns engine lookup and registration.
- Each engine implements `IDownloader`.
- Managers own shared concerns: config, queue, logging, progress, history, retry, proxy, cookies.
- Engine modules must stay isolated under `src/dler_kun/engines/<engine_id>/`.

## Engine Contract

Each engine should expose these capabilities when supported:

- `detect(url) -> bool`
- `download(request) -> DownloadResult`
- `crawl(request) -> CrawlResult`
- `ranking(request) -> RankingResult`
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

## Logging

Use these levels in user-visible logs:

- `[INFO]`
- `[DEBUG]`
- `[WARNING]`
- `[ERROR]`
- `[SUCCESS]`

Never log secrets, cookies, GoFile tokens, or raw authorization headers.

## Tests

For every detector, factory, manager, or adapter change, add or update tests under `tests/`.

Minimum verification before commit:

```powershell
python -m unittest discover tests
python -m dler_kun --help
python -m dler_kun detect https://gofile.io/d/example
```

When validating existing projects, prefer their public CLI/API and do not modify their code.
