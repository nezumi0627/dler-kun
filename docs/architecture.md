# Architecture

`dler-kun` keeps downloader-specific behavior behind engine adapters and centralizes shared application behavior in managers.

## Responsibility Flow

```text
CLI
  -> Application services
  -> ServiceDetector
  -> DownloaderFactory
  -> IDownloader Engine
  -> Existing Downloader
  -> DownloadManager / HistoryManager / LogManager
```

## Core Components

- `ServiceDetector`: maps URLs and crawl requests to service IDs.
- `DownloaderFactory`: registers and returns engine instances.
- `DownloadManager`: creates jobs, runs queue items, records results.
- `ConfigManager`: loads and saves JSON settings.
- `HistoryManager`: stores job history as JSON.
- `LogManager`: emits normalized user-visible log events.
- `ProgressManager`: stores current progress snapshots.

## Engine Isolation

```text
src/dler_kun/engines/
  dl/
  gofile/
  85xo/
```

Engine adapters use vendored engine code from `src/dler_kun/vendor/` by default. They may add those internal paths to `sys.path` or execute vendored CLIs, but they must not rewrite downloader internals unless explicitly planned.

## URL Detection

Pattern matching is intentionally simple and explicit:

- `gofile.io` -> `gofile`
- `85xo.com` -> `85xo`
- `tweetfile.com`, `twimg-media.com`, `cdn1.twimg-media.com` -> `dl`

Unknown URLs return `unsupported_service`.

## Data Files

Runtime files stay out of Git:

- `config.json`
- `history.json`
- `downloads/`
- `logs/`
- service tokens/cookies
