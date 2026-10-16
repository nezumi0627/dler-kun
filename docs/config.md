# 設定

設定は実行時のカレントディレクトリにある `config.json` から読み込みます。未作成なら既定値を使います。

```powershell
dler-kun config       # 有効設定を表示
dler-kun config --save # 既定値をconfig.jsonへ保存
```

## 既定値

```json
{
  "output_dir": "downloads",
  "threads": 3,
  "timeout": 30,
  "retry": 2,
  "language": "ja",
  "proxy": "",
  "cookie": "",
  "user_agent": "",
  "local_addr": "",
  "engine_paths": {"twimg": ""},
  "85xo": {"days": 10, "max_pages": 50, "network_capture_seconds": 15.0},
  "gofile": {"ranking_limit": 60, "max_more_clicks": 5, "ranking_seeds": []},
  "mvfile": {"api_base": "https://rwzugqnp.fun800.click/app-api", "timeout_seconds": 30.0}
}
```

設定は既定値と再帰的にマージされます。CLIで指定した `--proxy`、`--cookie`、`--user-agent`、`--local-addr`、タイムアウトは設定値を上書きします。

`85xo` の `days` と `max_pages` はクロール既定値です。`gofile.ranking_limit` はランキング要求数、`gofile.ranking_seeds` はランキングのURL配列です。`mvfile.api_base` はFun800 API基点です。`engine_paths.twimg` は旧vendor wrapper用に残してありますが、現行の既定routeはありません。

## 秘密情報

Cookie、proxyの認証情報、パスワードなどを含む設定ファイルをGitに追加しないでください。設定表示では秘密値を伏せます。コマンドライン引数はシェル履歴に残る場合があるため、共有端末ではCookie等を引数で渡さないでください。

## ユーザーデータ

ジョブ状態、履歴、キャッシュは `dler_kun2.infrastructure.state.paths.state_dir()` が返すローカル状態ディレクトリに保存します。出力先は `output_dir` または各コマンドの `-o` で指定します。
