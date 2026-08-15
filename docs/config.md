# 設定・キャッシュ・エラー

## config.json

`ConfigManager` がプロジェクトルートの `config.json` を読み込み、内蔵既定値と deep merge します。存在しない場合はメモリ上の既定値のみ使用。

```powershell
python -m dler_kun config --save   # 既定値をファイルに書き出し
python -m dler_kun config          # マージ後の有効値を表示
```

## 設定キー一覧

### トップレベル

| キー | 型 | 既定 | 説明 |
|------|-----|------|------|
| `output_dir` | string | `"downloads"` | 既定出力ディレクトリ |
| `threads` | int | `3` | スレッドプール（将来拡張用） |
| `timeout` | int | `30` | 一般タイムアウト秒 |
| `retry` | int | `2` | 失敗時の再試行回数（アプリ層） |
| `language` | string | `"ja"` | UI 言語（将来拡張用） |
| `proxy` | string | `""` | GoFile 等のプロキシ URL |
| `local_addr` | string | `""` | 全エンジン共通のソース IP バインド（例: iPhone USB テザリング `172.20.10.2`） |
| `cookie` | string | `""` | グローバル Cookie ヘッダ |
| `user_agent` | string | `""` | 空なら各エンジン既定 UA |
| `engine_paths` | object | 下記 | vendored パス override |

### `engine_paths`

| キー | 環境変数 | 説明 |
|------|----------|------|
| `twimg` | `DLER_TWIMG_PATH` | twimg スクリプトディレクトリ |

gofile / 85xo / mvfile / gofilerun はエンジン内に統合済みのため engine_paths は不要。

### `85xo`

| キー | 型 | 既定 | 説明 |
|------|-----|------|------|
| `default_seeds` | string[] | ja/vi latest-updates | クロール開始 URL |
| `days` | int | `10` | CLI `--days` 未指定時の遡及日数 |
| `max_pages` | int | `50` | シードあたり最大一覧ページ |
| `network_capture_seconds` | float | `15.0` | legacy: キャプチャ秒 |

**非推奨**: `default_seed`（単数）は読み込み時に `default_seeds` へ正規化され削除されます。

### `gofile`

| キー | 型 | 既定 | 説明 |
|------|-----|------|------|
| `ranking_seeds` | string[] | douga 4 + lab 4 | ランキングシード URL |
| `ranking_limit` | int | `60` | douga API `limit` |
| `max_more_clicks` | int | `5` | 互換用（現在未使用） |

`ranking_seeds` が空または未設定の場合、自動的に全既定シードが補完されます。

### `mvfile`

| キー | 型 | 既定 | 説明 |
|------|-----|------|------|
| `api_base` | string | `https://rwzugqnp.fun800.click/app-api` | land-page API 基点 |
| `timeout_seconds` | float | `30.0` | API / セグメント取得タイムアウト |

### 設定例

```json
{
  "output_dir": "downloads",
  "retry": 3,
  "proxy": "http://127.0.0.1:7890",
  "user_agent": "MyBot/1.0",
  "engine_paths": {
    "gofile": ""
  },
  "85xo": {
    "default_seeds": [
      "https://www.85xo.com/ja/latest-updates/"
    ],
    "days": 7,
    "max_pages": 30
  },
  "gofile": {
    "ranking_seeds": [
      "https://gofile-douga.com/new",
      "https://gofilelab.com/ja/popular-24h"
    ],
    "ranking_limit": 100,
    "max_more_clicks": 8
  }
}
```

---

## キャッシュ

### ファイル

| ファイル | 管理クラス | 用途 |
|----------|-----------|------|
| `download_cache.json` | `DownloadCacheManager` | URL キーごとの DL 状態 |
| `*.mp4.json` | vendored 85xo | メタデータ sidecar |

### CacheStatus

| 値 | 意味 |
|----|------|
| `complete` | 正常完了。次回 skip 対象 |
| `partial` | DL 途中（`.part` 存在） |
| `corrupt` | 破損・不完全。再 DL 前に削除 |
| `failed` | DL 失敗 |

### skip 判定（85xo fast）

次のいずれかを満たすと skip（`skip_existing` 有効時）:

1. `download_cache.json` に `status=complete` かつファイルサイズ一致
2. 対象ファイル + sidecar `.json` が存在しサイズ > 0

### 再 DL トリガー

次回実行前に:

- 完了扱いでない `.part` → 条件により削除
- 破損扱いのターゲットファイル → 削除して最初から

GoFile vendored 側も `.part` ファイルで再開・破棄を管理します。

mvfile / gofilerun（HLS）は `.hlsd` ステージングに取得済みセグメントを保持し、再実行時は未取得分だけ再取得してから remux します（完了済み `.mp4` はスキップ、失敗時はステージングを残して再開に備える）。

### キャッシュキー

85xo fast: URL ベースの `cache_key_for_url()`（adapter 経由で `DownloadCacheManager` に渡される）

---

## ジョブ状態（JobStatus）

| 値 | 説明 |
|----|------|
| `pending` | キュー投入直後 |
| `running` | 実行中 |
| `success` | 正常完了 |
| `failed` | 失敗 |
| `skipped` | スキップ |
| `unsupported` | 未対応機能 / 未知ジョブ |
| `cancelled` | ユーザーキャンセル |

---

## エラーコード

エンジン adapter 境界で正規化される `errors[]` の値:

| コード | 意味 |
|--------|------|
| `unsupported_service` | URL / サービス未対応 |
| `invalid_request` | リクエスト不正 |
| `not_found` | メディア未検出 |
| `auth_required` | 認証必要 |
| `network_error` | ネットワーク / API 失敗 |
| `download_failed` | ダウンロード失敗 |
| `crawl_failed` | クロール / ランキング失敗 |
| `dependency_missing` | 依存パッケージ不足（aiohttp 等） |

CLI 人間向け出力では `[ERROR]` タグと message が表示されます。

---

## ログレベル

`LogManager` / CLI 出力タグ:

| レベル | タグ | 用途 |
|--------|------|------|
| INFO | `[INFO]` | 開始・進行 |
| DEBUG | `[DEBUG]` | 詳細（将来拡張） |
| WARNING | `[WARNING]` | キャンセル等 |
| ERROR | `[ERROR]` | 失敗 |
| SUCCESS | `[SUCCESS]` | 正常完了 |

**禁止**: Cookie、GoFile トークン、Authorization ヘッダなど秘密情報のログ出力。

---

## 履歴

`history.json` に完了ジョブ（download / crawl / ranking）が append されます（最大 5000 件）。

---

## オプション依存関係

| 用途 | インストール |
|------|-------------|
| 開発・テスト | `pip install -e ".[dev]"` |
| 85xo legacy crawl | vendored 85xo の Chrome / Selenium 依存 |
| 85xo fast DL（推奨） | システム `curl`（あれば使用、なければ requests） |

本体 `dependencies`（`pyproject.toml`）: `requests`, `cryptography`, `aiofiles`, `aiohttp`, `aiohttp-socks`, `rich`, `tqdm`
