# Twimg ownership observation (2026-10-16, refreshed)

Sanitized public GET observations only:

- `https://twimg-media.com/` returned an HTML app shell.
- `https://tweetfile.com/` returned an HTML app shell.
- `twimg-media.com`, `video.twimg-image.com`, and `tweetfile.com` referenced
  `/assets/index-BLpblLBu.js`; `media-twimg.com` and `tweetplay.com` referenced
  `/assets/index-6z2BFjiU.js`.
- Both bundles contained the backend host `rwzugqnp.fun800.click` and the
  `/flow/land-page/getInfo` and `/flow/land-page/list_by_links_page` endpoint
  names, plus `netDiskInfo` response-field references. This is evidence of a
  Fun800/vll-style frontend, not evidence of the legacy vendored Twimg backend.
- `https://cdn1.twimg-media.com/` timed out during response read.
- `https://twimg.jp/` failed DNS resolution from the audit environment.

The bundle strings identify an apparent API family, but no representative
share-page request/response pair was verified. Do not infer that every alias
uses the same backend from the shared bundles alone. No Twimg host is registered
in v2; these aliases remain quarantined until representative share-page/API
evidence establishes ownership. The verified `video.twimg.it.com` Videy path
is tracked separately and does not establish ownership of these aliases.
