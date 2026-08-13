# クロール / ランキングのソース指定

収集対象は `--source` 別名か `--seed URL` で選べます。

- `--source ALIAS` — 短い別名で収集対象を指定
- `--seed URL` — 直接 URL を指定（別名にない URL も可）

---

## 85xo / 85po

```bash
# セクション別名
dler-kun crawl 85xo --source top-rated --download
dler-kun crawl 85xo --source most-popular
dler-kun crawl 85xo --source tags                  # タグ検索
dler-kun crawl 85xo --source home                  # 動画一覧
dler-kun crawl 85xo --source members               # 投稿者一覧
dler-kun crawl 85xo --source member-629 --download # 投稿者ページ
dler-kun crawl 85xo --source member-629-videos
dler-kun crawl 85xo --source member-629-friends
dler-kun crawl 85xo --source member-629-favorites  # お気に入り

# 直接 URL も指定可（85po.net / 85po.com も同様）
dler-kun crawl 85xo --seed https://www.85po.net/ --download
dler-kun crawl 85xo --seed https://www.85xo.com/ja/members/629/videos/
```

### `--source` 別名一覧（85xo）

| 別名 | URL |
|------|-----|
| `latest-updates` | https://www.85xo.com/ja/latest-updates/ |
| `home` | https://www.85xo.com/ja/ |
| `top-rated` | https://www.85xo.com/ja/top-rated/ |
| `most-popular` | https://www.85xo.com/ja/most-popular/ |
| `tags` | https://www.85xo.com/ja/tags/ |
| `members` | https://www.85xo.com/ja/members/ |
| `member-629` | https://www.85xo.com/ja/members/629/ |
| `member-629-videos` | https://www.85xo.com/ja/members/629/videos/ |
| `member-629-friends` | https://www.85xo.com/ja/members/629/friends/ |
| `member-629-favorites` | https://www.85xo.com/ja/members/629/favorites/videos/ |

---

## gofile-douga / gofilelab

```bash
# ランキング（別名で収集）
dler-kun ranking gofile --source douga              # gofile-douga.com 一覧
dler-kun ranking gofile --source lab                # gofilelab.com ランキング

# 直接 URL をシードに指定
dler-kun crawl gofile --seed https://gofile-douga.com/?sort=24h
dler-kun crawl gofile --seed https://gofilelab.com/ja/dl-ranking
```

### `--source` 別名一覧（gofile）

| 別名 | URL |
|------|-----|
| `douga` / `home` | https://gofile-douga.com/ |
| `new` | https://gofile-douga.com/new |
| `24h` | https://gofile-douga.com/?sort=24h |
| `3days` | https://gofile-douga.com/?sort=3days |
| `lab` / `popular-24h` | https://gofilelab.com/ja/popular-24h |
| `popular-30d` | https://gofilelab.com/ja/popular-30d |
| `newest` | https://gofilelab.com/ja/newest |
| `dl-ranking` | https://gofilelab.com/ja/dl-ranking |

---

## 補足

- 一覧ページ（gofile-douga / gofilelab など）を `download` に渡すと、一覧全体を取得します（crawl と同じ動作）。
- ランキングのオプション詳細は [ranking.md](ranking.md) を参照。
