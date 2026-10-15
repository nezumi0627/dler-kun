# Twimg ownership observation (2026-10-16)

Sanitized public GET observations only:

- `https://twimg-media.com/` returned an HTML app shell.
- `https://tweetfile.com/` returned an HTML app shell.
- Both root pages referenced `/assets/index-BLpblLBu.js`; a sanitized shell is
  retained in `public-app-shell.html`.
- A public GET of that bundle contained none of the endpoint markers or
  backend identifiers used by the vendored tool.
- `https://cdn1.twimg-media.com/` timed out during response read.
- `https://twimg.jp/` failed DNS resolution from the audit environment.

The two responding roots alone do not establish that their pages use the same
backend as the vendored Twimg tool, nor distinguish them from mvfile. No Twimg
host is registered in v2; these aliases remain quarantined until representative
share-page/API evidence establishes ownership.
