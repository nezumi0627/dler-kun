# 運用・レート制限・トラブルシューティング

## レート制限

共有HTTP runtimeはoriginごとに並列数を制限し、HTTP 429の `Retry-After` が秒数またはHTTP日付なら待機します。待機が設定上限を超える場合は `rate_limited` として終了します。IP、proxy、account、token、User-Agentを切り替えて制限を回避しません。

## エラーコード

| Code | 意味 |
|---|---|
| `unsupported_service` | route未登録 |
| `ambiguous_service` | backendを安全に特定できない |
| `unsupported_capability` | engineがその操作を実装していない |
| `invalid_request` | URL、option、設定が不正 |
| `not_found` | shareまたはsourceが見つからない |
| `auth_required` | サイト側で認証が必要 |
| `network_error` | 接続、timeout、HTTP応答の問題 |
| `rate_limited` | retry waitが設定上限を超えた |
| `download_failed` / `crawl_failed` | 取得処理に失敗 |
| `dependency_missing` | optional runtime/toolが不足 |
| `cancelled` | cancel要求で処理を停止 |

## よくある確認

- routeが見つからない: `dler-kun detect URL` と `dler-kun sites --json` を確認。未検証hostは意図的に隔離されています。
- 空のcrawl結果: 公開ページ/APIの仕様変更、シードURL、期間、ページ上限を確認してください。
- 429: `Retry-After` の時間を待ってから再実行。短時間に繰り返し再試行しないでください。
- HLS処理が失敗: 対象エンジンの依存と `ffmpeg` が必要か確認。転送中止後の `.part` / HLS stagingは成功ファイルとして数えないでください。
- JSONにURLが必要: 公開payloadは署名付きmedia URLを意図的に省略します。診断ログに秘密URLを出さないでください。

## 安全な報告

不具合報告にはコマンド、engine、公開可能なerror code、発見数/完了数を含めます。Cookie、署名URL、認証token、個人情報を含む媒体名は貼り付けないでください。
