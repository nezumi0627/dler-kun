# Architecture

`dler-kun` keeps downloader-specific behavior behind engine adapters and centralizes shared application behavior in managers.

## Responsibility Flow

```text
UI
  -> Application API / CLI
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

Engine adapters may add paths to `sys.path` or execute existing CLIs, but they must not change downloader internals.

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
