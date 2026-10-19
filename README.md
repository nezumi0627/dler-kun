# dler-kun2

`dler-kun2` は旧 `dler-kun` の履歴を引き継いだ後継実装です。公開リポジトリは `nezumi0627/dler-kun` です。インストール後のコマンド名は **`dler-kun`** です。

複数のメディアサービスを、共通の URL 判定・クロール・保存・エラー形式で扱う Python 3.10+ の CLI です。確認できたサービスだけをルート登録し、未確認の別名は誤配信を避けるため拒否します。

## セットアップ

```powershell
git clone https://github.com/nezumi0627/dler-kun.git
cd dler-kun
python -m venv .venv
.\.venv\Scripts\Activate.ps1   # Windows PowerShell
# source .venv/bin/activate     # macOS / Linux
python -m pip install -e .
dler-kun --help
```

開発ツールを含める場合:

```powershell
python -m pip install -e ".[dev,browser]"
```

## 対応エンジン

CLI の `dler-kun sites --json` が現在の登録内容です。ホスト名だけでなく、必要なサービスではパスやバックエンド識別子も判定します。

| Engine | 登録対象 | download | crawl | ranking |
|---|---|:---:|:---:|:---:|
| `gofile` | `gofile.io`、ランキングページの `gofile-douga.com` / `gofilelab.com` | ✓ | ✓ | ✓ |
| `gofilerun` | `gofile.run` | ✓ | ✓ | — |
| `85xo` | `85po.net` | ✓ | ✓ | — |
| `linkex` | `l2e.click/i/...` | ✓ | ✓ | — |
| `mixixxx` | `mixi-xxx.cc`、`jav-mixi.cc` | ✓ | ✓ | — |
| `mvfile` | Fun800/VLL API を確認した共有ホスト。詳細は [engines.md](docs/engines.md) | ✓ | ✓ | — |
| `videy` | `videy.co`、`video.twimg.it.com`、`media.twimg.date` | ✓ | — | — |

`twimg` の旧vendor adapterは保管していますが、現在そのCLIルートは登録していません。確認済みのTwimg風共有ホストはFun800系バックエンドを使うため、`mvfile` に登録しています。未確認のホストは名前だけで振り分けません。

## 使い方

```powershell
# URL の判定
dler-kun detect https://gofile.io/d/EXAMPLE

# 共有URLのダウンロード
dler-kun download https://gofile.io/d/EXAMPLE

# クロール結果の確認。--download を付けると保存も実行
dler-kun crawl 85xo --days 15
dler-kun crawl 85xo --days 15 --download

# GoFile ランキング
dler-kun ranking gofile --source douga --download

# 機械処理向け JSON
dler-kun --json sites
```

全コマンドは `dler-kun --help`、各コマンドの引数は `dler-kun <command> --help` で確認できます。

## ドキュメント

- [インストール](docs/install.md)
- [CLI リファレンス](docs/cli.md)
- [エンジンとURLルーティング](docs/engines.md)
- [設定](docs/config.md)
- [アーキテクチャ](docs/architecture.md)
- [運用・レート制限・トラブルシューティング](docs/operations.md)

## 開発時の確認

```powershell
python -m ruff check src/dler_kun2 tests
python -m basedpyright
python -m pytest -q
python -m dler_kun2 --help
python -m dler_kun2 sites --json
```

## 安全な利用

権利のあるコンテンツと、各サイトの利用条件に従って使用してください。認証・DRM・アクセス制限を回避しません。HTTP 429 と `Retry-After` を尊重し、IP・アカウント・token の切替で制限を回避しません。Cookie、署名付きURL、認証情報はログや公開結果に含めないでください。

## ライセンス

本体は [MIT License](LICENSE) です。統合コード、vendor、外部ツールの情報は [NOTICE](NOTICE) を参照してください。
