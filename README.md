# dler-kun

`dler-kun` は、複数の既存ダウンローダーを 1 つの UI、1 つの設定、1 つのキューで扱う統合ダウンロードプラットフォームです。

## 対応エンジン

- `dl`: `tweetfile.com` / `twimg-media.com` 系の既存 Python ダウンローダー
- `gofile`: `gofile.io` の既存非同期ダウンローダー
- `85xo`: `85xo.com` の既存 crawler/downloader

## 最重要方針

既存ダウンロード処理、暗号化、クロール、保存、リトライなどの内部ロジックは変更しません。`dler-kun` 側は Service Detector、Factory、Manager、Engine Adapter、UI だけを担当します。

```text
URL / Crawl Request
  -> ServiceDetector
  -> DownloaderFactory
  -> Engine Adapter
  -> Existing Downloader
  -> DownloadManager / Progress / History / Log
```

## セットアップ

```powershell
cd E:\projects\dler-kun
python -m venv .venv
.\.venv\Scripts\python -m pip install -e .[dev,web]
```

既存プロジェクトの処理は `src/dler_kun/vendor/` に取り込み済みです。通常利用では `E:\projects\dl`、`E:\projects\gofile-downloader`、`E:\projects\85-xo` は不要です。

開発時だけ外部実装を一時的に試す場合は、`config.json` または環境変数 `DLER_DL_PATH`、`DLER_GOFILE_PATH`、`DLER_85XO_PATH` で上書きできます。

## CLI

```powershell
# URL自動判別
python -m dler_kun download https://gofile.io/d/example

# 複数URL一括投入
python -m dler_kun download https://tweetfile.com/example https://gofile.io/d/example

# 85xoを10日前まで高速クロールしてダウンロード
python -m dler_kun crawl 85xo --days 10 --download --method fast --parallel-downloads 4 --download-read-timeout 30 --download-attempts 2

# Web UI
python -m dler_kun web
```

## Web UI

`python -m dler_kun web` を実行すると、ローカル Web UI が起動します。

- Home: URL入力、現在速度、待機/完了/失敗、実行中 Engine
- Downloads: 進捗、速度、残り時間、保存先、Engine
- Crawl: 期間指定、収集結果、複数選択、一括ダウンロード
- Ranking: Engine の既存ランキング機能がある場合に表示
- History: 過去ジョブの検索、フィルター
- Settings: 保存先、Thread、Proxy、Cookie、User-Agent、Retry

## テスト

```powershell
python -m unittest discover tests
python -m dler_kun --help
python -m dler_kun detect https://gofile.io/d/example
```

## 85xo crawl

完成確認後の実行コマンド:

```powershell
python -m dler_kun crawl 85xo --days 10 --download --output-dir downloads/85xo --method fast --parallel-downloads 4 --download-read-timeout 30 --download-attempts 2
```

85xo の既定は高速方式です。一覧ページの日付で10日以内の候補を絞り、動画ページHTML内の `get_file` URL から最高 `br` の mp4 を選び、保存処理は vendored 85xo downloader の保存関数へ渡します。`--parallel-downloads` で同時ダウンロード数、`--download-read-timeout` と `--download-attempts` で詰まり時の打ち切りを指定できます。

従来の headless Chrome ネットワークキャプチャ方式に戻す場合:

```powershell
python -m dler_kun crawl 85xo --days 10 --download --method legacy
```
