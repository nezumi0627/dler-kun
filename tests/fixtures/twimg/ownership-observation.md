# Twimg-named host backend audit (2026-10-16)

The public bundles were fetched from the listed hosts and SHA-256 compared.
All observed app bundles use `https://rwzugqnp.fun800.click/app-api`, call
`/flow/land-page/getInfo` and `/flow/land-page/list_by_links_page`, and parse
`netDiskInfo`. The frontend requests `getInfo` with the current host passed as
the `domain` parameter. This is the Fun800/vll contract used by `mvfile`, not
the legacy Twimg vendor API.

| Host | Bundle path | SHA-256 prefix | Group |
| --- | --- | --- | --- |
| `twimg-media.com` | `/assets/index-BLpblLBu.js` | `e25fc692a426e7e91de01a0d819cacb60d643dbb020b7d26b8de32c59f32264f` | A |
| `cdn1.twimg-media.com` | `/assets/index-BLpblLBu.js` | same as A | A |
| `video.twimg-image.com` | `/assets/index-BLpblLBu.js` | same as A | A |
| `tweetfile.com` | `/assets/index-BLpblLBu.js` | same as A | A |
| `twfiles.com` | `/assets/index-BLpblLBu.js` | same as A | A |
| `media-twimg.com` | `/assets/index-6z2BFjiU.js` | `ab3c23783fe8cd3772ce7fe46168e38fa22e679b9fcbaa83766aef7e5bd2d389` | B |
| `cdn.twimg1.com` | `/assets/index-6z2BFjiU.js` | same as B | B |
| `twimg1.com` | `/assets/index-6z2BFjiU.js` | same as B | B |
| `twimg-album.com` | `/assets/index-6z2BFjiU.js` | same as B | B |

`tweetfile.com` is already a known Fun800/mvfile host. Exact bundle equality
therefore links groups A and B to the same first-party API contract. A GET to
the API with a deliberately invalid identifier and `domain=twimg-media.com`
returned HTTP 200, envelope keys `code,data,msg`, `data` keys
`info,rules,shortLink`, `rules.status=2`, and `info=null`. The sanitized
response is in `fun800-invalid-info.json`. This validates the missing-share
response shape; it is not a valid-share media fixture.

The following remain quarantined because a matching app/API contract was not
observed: `twimg.jp` (DNS failure), `video.twimg.jp`, `video.twimg1.com`,
`file-bio.com` (DNS failure), `gofile.video` (DNS failure), `gofile.trade`
(no app bundle), and `video.twimg.news`. Their names alone do not establish
ownership. The verified `video.twimg.it.com` direct-media route remains Videy.
