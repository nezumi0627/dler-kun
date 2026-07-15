# Engines

## `twimg`

Vendored source: `src/dler_kun/vendor/twimg/download_twitter_media.py`

Supported URL patterns:

- `tweetfile.com`
- `twimg-media.com`
- `cdn1.twimg-media.com`

Primary existing entry:

- `download_twitter_media.py`
- CLI: `python download_twitter_media.py <URL> [URL ...] -o <output>`
- Internal entry: `process_url(page_url, base_dir, args, db)`

Integration choice:

- Use the existing CLI boundary for download jobs because it preserves side effects, logging, SQLite state, and dependency bootstrap exactly as implemented.

## `gofile`

Vendored source: `src/dler_kun/vendor/gofile/`

Supported URL patterns:

- `gofile.io/d/<id>`

Primary existing entry:

- `gofile_dl.downloader.GoFileDownloader`
- `await downloader.init()`
- `await downloader.download(url_or_id, password=None, output_dir=...)`

Ranking source:

- `ranking_dl.py` contains existing GoFile ranking/new crawler behavior.

Integration choice:

- Import the package and call `GoFileDownloader` directly.
- Keep GoFile token/proxy handling inside the existing implementation.

## `85xo`

Vendored source: `src/dler_kun/vendor/xo85/`

Supported URL patterns:

- `85xo.com`
- `www.85xo.com`

Primary existing entries:

- `xo_dler.crawl_once(CrawlConfig(...))`
- `xo_dler.download_items(items, DownloadConfig(...))`
- CLI: `scripts/dler.py`, `scripts/crawler.py`, `scripts/scan.py`

Integration choice:

- Default to the `fast` adapter path in `dler-kun`: parse listing dates and video-page `get_file` links over HTTP, then pass normalized media items to the existing `download_items` saver.
- Keep the original `xo_dler.crawl_once` browser/network crawler available with `--method legacy`.
- Do not require the source project in `E:\projects\85-xo` at runtime.

Important limitation:

- `fast` mode depends on listing date text and video-page `uploadDate` / `get_file` HTML.
- `legacy` mode depends mainly on media `Last-Modified` data. Undated items are excluded unless explicitly included.
