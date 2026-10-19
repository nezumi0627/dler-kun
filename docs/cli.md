# CLI リファレンス

起動方法:

```powershell
dler-kun [--json] <command> [options]
python -m dler_kun2 [--json] <command> [options]
```

## コマンド

| コマンド | 用途 |
|---|---|
| `detect URL` | 登録済みエンジンと route を判定 |
| `sites` | エンジン、ホスト、能力を表示 |
| `download URL...` | URLを1件または複数件ダウンロード |
| `crawl SERVICE` | サービスを列挙。`--download` 指定時は保存 |
| `ranking SERVICE` | 対応するランキング一覧を取得。現行対象はGoFile |
| `jobs` | 永続化されたジョブ状態を表示 |
| `cancel JOB_ID` / `cancel --all` | 実行中ジョブへキャンセル要求 |
| `config` | 有効設定を表示。`config --save` で既定値を書き出す |

全引数は `dler-kun <command> --help` で確認できます。全コマンドで `--json` を指定すると JSON を出力します。

## よく使う例

```powershell
# route確認
dler-kun detect https://gofile.io/d/EXAMPLE

# 1件ダウンロード
dler-kun download https://gofile.io/d/EXAMPLE

# 85xoを直近15日分クロール。取得だけなら --download を外す
dler-kun crawl 85xo --days 15 --download

# GoFileランキング
dler-kun ranking gofile --source douga --download

# 設定済みのエンジンとホストをJSONで確認
dler-kun --json sites
```

## 共通オプション

`download`、`crawl`、`ranking` で使えるオプションには、`-o/--output-dir`、`--proxy`、`--user-agent`、`--cookie`、`--local-addr`、`--timeout-seconds`、`--metadata` があります。対応範囲はエンジンごとに異なるため、個別の `--help` も確認してください。

`download` は `--parallel-urls` でURL単位の並列数を制限します。mvfileの関連一覧を1項目だけに限定するには `--single` を使います。クロールや転送の並列設定には `--parallel-downloads`、`--discover-workers`、`--resolve-workers`、`--hls-workers`、`--segment-concurrency` があります。`--god` は各上限内で並列度を上げます。

## 結果と終了状態

既定の出力は短いサマリーです。JSON結果には要求数、発見数、完了数、利用不可数、正規化されたエラーが含まれます。署名付きメディアURLは公開payloadに含めません。

詳細な引数とエラーは `dler-kun <command> --help` および [運用ガイド](operations.md) を参照してください。
