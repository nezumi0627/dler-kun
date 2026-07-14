# UI / UX Design

`dler-kun` is a daily-use downloader UI. It should feel fast, direct, and readable even when the queue or history contains thousands of items.

## Visual Direction

- Dark theme by default
- Minimal Windows 11-like layout
- High contrast for states and progress
- Compact but readable spacing
- Subtle, fast transitions only

## Global Layout

```text
Left Navigation
  Home
  Downloads
  Crawl
  Ranking
  History
  Settings
  About

Right Content
  Top: active task strip
  Main: page content
  Bottom: collapsible color-coded log
```

## Home

Home is a dashboard:

- URL input supporting multiple lines
- Download button
- Crawler quick start
- Running, queued, completed, failed counts
- Current speed, ETA, total downloaded bytes
- CPU and memory placeholders for future native integration
- Current engine

## Downloads

Downloads is the primary management surface:

- Thumbnail slot
- Title
- Service
- State
- Speed
- Size
- Progress bar
- ETA
- Save path
- Started at
- Expected finish
- Engine

Rows should support details, filtering, sorting, and search.

## Crawl

Split view:

- Left: seed URL, service, days, ranking/search fields
- Right: collected results with thumbnail, title, author, date, size, duration, downloadable flag, checkbox

The normal flow must be:

```text
Fetch -> Review -> Select -> Add to Queue
```

## Ranking

If an engine has an existing ranking crawler, expose it without inventing a new ranking algorithm.

## Logs

Logs are collapsible and color-coded:

- `INFO`
- `SUCCESS`
- `WARNING`
- `ERROR`
- `DEBUG`

Clicking a log entry should show details when available.

## Performance

Large lists must be designed for virtualization or incremental rendering. The current static web UI limits DOM work and keeps rendering data-driven so it can be replaced by virtual rows later.
