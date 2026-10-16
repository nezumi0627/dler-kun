# エンジンとURLルーティング

この表はコード上で登録しているrouteです。`dler-kun sites --json` を実行すると、その環境の実際の登録一覧を確認できます。外部サイトの仕様変更や地域差による到達性までは保証しません。

| Engine | 現在のroute | 主な機能 |
|---|---|---|
| `gofile` | `gofile.io`; `gofile-douga.com` と `gofilelab.com` のランキング判定対象URL | download、crawl、ranking |
| `gofilerun` | `gofile.run` | download、crawl |
| `85xo` | `85po.net` | download、期間指定crawl |
| `linkex` | `l2e.click/i/...` | download、crawl |
| `mixixxx` | `mixi-xxx.cc`、`jav-mixi.cc` | download、crawl |
| `mvfile` | 下記のFun800/VLL共有ホスト | download、関連一覧crawl |
| `videy` | `videy.co`、`video.twimg.it.com` | download |

### mvfileの登録ホスト

`www.`付きのhostも登録しているものは両方記載しています。`cdn2.image-share.cc` は記載どおりのhostのみです。

- `tweetfile.com`、`www.tweetfile.com`
- `gofile.website`、`www.gofile.website`
- `image-share.cc`、`www.image-share.cc`、`cdn2.image-share.cc`
- `tweetplay.com`、`www.tweetplay.com`
- `imagedist.com`、`www.imagedist.com`
- `gofile.rocks`、`www.gofile.rocks`
- `gofile.bar`、`www.gofile.bar`
- `gofile.pl`、`www.gofile.pl`
- `twimg-media.com`、`www.twimg-media.com`、`cdn1.twimg-media.com`、`www.cdn1.twimg-media.com`
- `video.twimg-image.com`、`www.video.twimg-image.com`
- `media-twimg.com`、`www.media-twimg.com`
- `cdn.twimg1.com`、`www.cdn.twimg1.com`
- `twimg1.com`、`www.twimg1.com`
- `twimg-album.com`、`www.twimg-album.com`
- `twfiles.com`、`www.twfiles.com`

## ルーティングの注意

- `gofile.rocks`、`gofile.website`、`gofile.run` は `gofile.io` の別名として扱いません。バックエンドが異なります。
- `gofile-douga.com` と `gofilelab.com` は、ランキングソースとして識別できるURLに限って GoFile エンジンへ渡します。
- `l2e.click` は `/i/` の共有パスを条件にします。
- `twimg-media.com`、`cdn1.twimg-media.com`、`video.twimg-image.com`、`media-twimg.com`、`cdn.twimg1.com`、`twimg1.com`、`twimg-album.com`、`twfiles.com` は確認済みFun800系のため `mvfile` が処理します。Twimg風の名称だけでX公式CDNとは判断しません。
- `twimg` vendor adapterは保管していますが、現在のCLI routeには登録していません。
- `85xo.com`、`85po.com`、`twimg.jp`、その他の未確認別名は `UNVERIFIED_HOSTS` に隔離し、対応済みとは表示しません。

## 能力

対応していない機能は `unsupported_capability` を返します。ログイン機能は現行CLIで提供していません。エンジン単位の能力値は `sites --json` の `capabilities` を参照してください。
