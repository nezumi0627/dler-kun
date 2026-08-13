# dler-kun

<p align="center">
  <img src=".github/assets/banner.png" alt="dler-kun" width="100%">
</p>

複数サイトのメディアを、ひとつの CLI でダウンロードするツール。URL を渡せば対応サイトを自動判定し、単発ダウンロードからランキング収集・期間指定クロールまで同じコマンド体系で扱えます。

```bash
dler-kun download https://gofile.io/d/example -o downloads
dler-kun crawl 85xo --days 15 --download
dler-kun crawl 85xo --days 365 --source top-rated --download --discover-workers 12 --resolve-workers 12 --parallel-downloads 8
dler-kun ranking gofile --source douga --download
```

<p align="left">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.10%2B-blue?style=flat-square">
  <img alt="License" src="https://img.shields.io/badge/License-Unlicense-blue?style=flat-square">
  <img alt="Platform" src="https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey?style=flat-square">
</p>

> **免責事項** — このツールは**実験・教育目的**のものです。著作権や利用条件に違反するコンテンツの取得には使わないでください。対象サイトとは一切無関係です。**DRM の回避や認証の突破は行いません**。利用者は各自の国の法律・対象サイトの利用規約を遵守する責任があります。詳細は [LEGAL.md](LEGAL.md) を参照。

---

## 目次

- [特徴](#特徴)
- [インストール](#インストール)
- [使い方](#使い方)
- [対応サイト](#対応サイト)
- [設定](#設定)
- [ドキュメント](#ドキュメント)
- [ライセンス](#ライセンス)

---

## 特徴

- **自動判定** — URL から対応サイトを選択
- **一括ダウンロード** — 複数 URL をまとめて処理
- **クロール / ランキング** — 一覧・人気順から収集して DL
- **高速クロール** — 85xo の一覧取得・URL解決・DL を並列化（`--discover-workers` / `--resolve-workers` / `--parallel-downloads`）
- **mixixxx 並列DL** — 署名付き HLS を Chrome 経由で取得し、動画単位（`--parallel-downloads`）とセグメント単位（`--segment-concurrency`）で並列化
- **キャッシュ** — 完了済みファイルをスキップ、失敗途中は再開、fast-capture（動画URL解決）もキャッシュして再クロールを高速化
- **設定ファイル** — `config.json` で出力先・リトライなどを管理

---

## インストール

```bash
git clone https://github.com/nezumi0627/dler-kun.git
cd dler-kun
python -m venv .venv
.\.venv\Scripts\Activate.ps1   # Windows (PowerShell)
source .venv/bin/activate      # macOS / Linux
pip install -e .
```

開発用依存: `pip install -e ".[dev]"`

### どこでも使えるように（PATH 登録）

venv の `dler-kun.exe` を PATH に通せば、**cmd / PowerShell / bash のどこからでも** `dler-kun` と打てます。

1. シムを置くディレクトリを作り、`dler-kun.cmd`（cmd 用）と `dler-kun`（bash 用）を配置。`<プロジェクトのパス>` は dler-kun のインストール先（リポジトリのある場所）に置き換える:

   `~/dler-kun-bin/dler-kun.cmd`:
   ```cmd
   @echo off
   "<プロジェクトのパス>\.venv\Scripts\dler-kun.exe" %*
   ```
   `~/dler-kun-bin/dler-kun`（`chmod +x` する）:
   ```sh
   #!/bin/sh
   exec "<プロジェクトのパス>/.venv/bin/dler-kun" "$@"
   ```
   > venv 内のコマンドの場所は OS で異なる: Windows は `.venv\Scripts\dler-kun.exe`、macOS / Linux は `.venv/bin/dler-kun`。
2. ディレクトリをユーザー PATH に追加:
   ```powershell
   [Environment]::SetEnvironmentVariable('Path', [Environment]::GetEnvironmentVariable('Path','User').TrimEnd(';') + ';' + "$HOME\dler-kun-bin", 'User')
   ```
3. **新しいターミナル**を開けば使えます。

---

## 使い方

```bash
dler-kun detect <url>                        # サイト判定
dler-kun download <url> [<url> ...] [-o DIR] # ダウンロード（複数可）
dler-kun crawl 85xo --days 15 --download     # 期間指定クロール（最新15日分）
dler-kun ranking gofile --source douga --limit 60   # ランキング収集
dler-kun sites                               # 対応サイト一覧
dler-kun config                              # 設定表示
```

| コマンド | 説明 |
|---------|------|
| `detect <url>` | URL がどのサイトか判定 |
| `download <url>...` | URL をダウンロード |
| `crawl <service> [--seed/--source] [--days] [--download]` | 一覧・投稿者ページから収集して DL（85xo / gofile / gofilerun / mvfile） |
| `ranking <service> [--source] [--limit] [--download]` | ランキングから収集（gofile） |
| `sites [--json]` | 対応サイト一覧 |
| `config [--save]` | 設定を表示 / 書き出し |
| `cancel [JOB_ID \| --all]` | 実行中ジョブをキャンセル |

出力は短いサマリーが既定。詳細 JSON は `--json`。`python -m dler_kun ...` でも同じです。

---

## 対応サイト

| Site | 対象 | download | crawl | ranking |
|------|------|:--------:|:-----:|:-------:|
| **gofile** | gofile.io | ✓ | | |
| **gofile-douga** | gofile-douga.com（動画一覧） | ✓ | ✓ | ✓ |
| **gofilelab** | gofilelab.com（ランキング） | ✓ | ✓ | ✓ |
| **gofilerun** | gofile.run | ✓ | ✓ | |
| **85xo** | 85xo.com · 85po.net · 85po.com | ✓ | ✓ | |
| **twimg** | twimg-media | ✓ | | |
| **mvfile** | mvfile.com · tweetfile.com · gofile.website | ✓ | ✓ | |
| **videy** | video.twimg.news · videy.co | ✓ | | |
| **mixixxx** | mixi-xxx.cc | ✓ | ✓ | |

クロール / ランキングのソース指定（`--source` 別名一覧）は [docs/sources.md](docs/sources.md) を参照。

---

## 設定

`config.json` で動作を調整します（`dler-kun config --save` で既定値を書き出し）。

| Key | 概要 |
|-----|------|
| `output_dir` | 既定の保存先 |
| `retry` | 失敗時の再試行回数 |
| `85xo.*` / `gofile.*` | シード・limit など |

詳細: [docs/config.md](docs/config.md)

---

## ドキュメント

| Doc | Contents |
|-----|----------|
| [cli.md](docs/cli.md) | コマンド・オプション・終了コード |
| [sources.md](docs/sources.md) | クロール/ランキングのソース別名（85xo / gofile） |
| [ranking.md](docs/ranking.md) | GoFile ランキングソース |
| [config.md](docs/config.md) | 設定・キャッシュ・エラーコード |
| [architecture.md](docs/architecture.md) | 内部構成 |
| [engines.md](docs/engines.md) | サイトごとの能力 |

テスト・品質チェック:

```bash
pip install -e ".[dev]"
python -m pytest                # テスト
python -m ruff check src/dler_kun   # リント
python -m basedpyright          # 型チェック
```

---

## ライセンス

[Unlicense](LICENSE) — パブリックドメイン相当（yt-dlp と同様）。自由にコピー・変更・再配布できます。vendored エンジン（`src/dler_kun/vendor/`）はプロジェクト由来のコードで、このライセンスの対象です。
