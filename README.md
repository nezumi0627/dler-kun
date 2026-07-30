# dler-kun

**複数サイトのメディアを、ひとつの CLI でダウンロードするツール。**

URL を渡せば対応サイトを自動判定。単発ダウンロードから、ランキング収集・期間指定クロールまで同じコマンド体系で扱えます。

```bash
pip install -e .
dler-kun detect https://gofile.io/d/example
dler-kun download https://gofile.io/d/example -o downloads
```

<p align="left">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.10%2B-blue?style=flat-square">
  <img alt="License" src="https://img.shields.io/badge/License-MIT-green?style=flat-square">
  <img alt="Platform" src="https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey?style=flat-square">
</p>

---

## Features

- **自動判定** — URL から対応サイトを選択
- **一括ダウンロード** — 複数 URL をまとめて処理
- **クロール / ランキング** — 一覧・人気順から収集して DL
- **進捗表示** — 端末幅に合わせたコンパクトなプログレスバー
- **キャッシュ** — 完了済みファイルは次回スキップ
- **設定ファイル** — `config.json` で出力先・リトライなどを管理

## Supported sites

| Site | 対象 | download | crawl | ranking |
|------|------|:--------:|:-----:|:-------:|
| **twimg** | tweetfile / twimg-media | ✓ | | |
| **gofile** | gofile.io · gofile-douga · gofilelab | ✓ | ✓ | ✓ |
| **85xo** | 85xo.com | ✓ | ✓ | |
| **mvfile** | mvfile.com / cdn.mvfile.com | ✓ | ✓ | |

---

## Install

```bash
git clone https://github.com/nezumi0627/dler-kun.git
cd dler-kun
python -m venv .venv

# Windows (PowerShell)
.\.venv\Scripts\Activate.ps1

# macOS / Linux
source .venv/bin/activate

pip install -e .
```

開発用依存:

```bash
pip install -e ".[dev]"
```

---

## Quick start

出力は短いサマリーが既定。詳細 JSON が必要なときだけ `--json` を付けてください。

```bash
# サイト判定
dler-kun detect https://gofile.io/d/example

# URL ダウンロード
dler-kun download https://tweetfile.com/example https://gofile.io/d/example

# mvfile 共有リンク
dler-kun download https://cdn.mvfile.com/3EN1gA -o downloads/mvfile

# 85xo — 直近 10 日をクロールして DL
dler-kun crawl 85xo --days 10 --download -o downloads/85xo

# GoFile ランキングを収集して DL
dler-kun ranking gofile --download --limit 60 -o downloads/gofile

# 設定
dler-kun config
dler-kun config --save
```

`python -m dler_kun ...` でも同じです。

---

## Usage

### Download

```bash
dler-kun download <url> [<url> ...] [-o DIR]
```

### GoFile ranking

人気順・新着などから URL を集め、そのままダウンロードできます。

```bash
# 全ソース（既定）
dler-kun ranking gofile --download

# douga の 24h のみ
dler-kun ranking gofile --source douga --source 24h --limit 30

# lab の popular-30d
dler-kun ranking gofile --source popular-30d
```

ソース一覧は [docs/ranking.md](docs/ranking.md)。

### 85xo crawl

```bash
# 高速クロール（既定）
dler-kun crawl 85xo --days 10 --download --method fast --parallel-downloads 4

# ブラウザキャプチャ方式
dler-kun crawl 85xo --days 10 --download --method legacy
```

---

## Configuration

`config.json` で動作を調整します。

| Key | 概要 |
|-----|------|
| `output_dir` | 既定の保存先 |
| `retry` | 失敗時の再試行回数 |
| `85xo.*` | シード・日数・並列など |
| `gofile.*` | ランキングシード・limit など |

```bash
dler-kun config --save   # 既定値を書き出し
dler-kun config          # 有効設定を JSON 表示
```

詳細: [docs/config.md](docs/config.md)

---

## Cache

完了済みファイルは `download_cache.json` と sidecar（`*.mp4.json`）を見てスキップします。途中失敗の `.part` は次回実行前に破棄して再 DL します。

---

## Docs

| Doc | Contents |
|-----|----------|
| [cli.md](docs/cli.md) | コマンド・オプション・終了コード |
| [ranking.md](docs/ranking.md) | GoFile ランキングソース |
| [config.md](docs/config.md) | 設定・キャッシュ・エラーコード |
| [architecture.md](docs/architecture.md) | 内部構成 |
| [engines.md](docs/engines.md) | サイトごとの能力 |

---

## Test

```bash
python -m unittest discover tests
dler-kun --help
dler-kun detect https://gofile.io/d/example
```

---

## License

MIT
