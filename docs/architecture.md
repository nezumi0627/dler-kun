# アーキテクチャ

```text
CLI (presentation)
  -> application services (download / crawl / ranking)
  -> EngineRegistry (verified host and path rules)
  -> engines/<engine_id> (site API, parser, adapter)
  -> shared infrastructure (HTTP, rate limits, transfer, storage, state)
```

## レイヤーの責務

- **domain**: immutable request、download plan、結果、共通error code。
- **application**: engine選択後の処理順、共通転送、部分結果の集計。
- **routing**: 検証済みhost/path ruleとエンジン登録。未確認aliasをquarantine。
- **engines**: site-specific APIとparser。共有HTTPや保存先の実装を重複させない。
- **infrastructure/http**: 接続pool、timeout、origin単位の並列制限、Retry-After、cancel。
- **infrastructure/storage**: 一意な出力名、root配下への保存、atomic transfer、HLS staging。
- **infrastructure/state**: 設定、job状態、history、cache。
- **presentation/cli**: 引数検証と短い標準出力。JSONは公開可能な結果だけを返す。

## Route追加手順

1. 公開ページと参照APIの応答形を確認し、既存バックエンドとの違いを記録する。
2. `routing/defaults.py` にrouteを追加する。パス判定が必要なhostでは `backend_probe` を設定する。
3. `tests/test_v2_routing.py` に正しいrouteと誤routeしないケースを追加する。
4. エンジン固有parserにはsanitized fixtureを使い、署名URLやcookieをfixtureに残さない。

ホスト名の類似だけではrouteを決めません。共有hostのbackendを識別できない場合は拒否します。

## 失敗と秘密値

engine adapterは例外を共通 `EngineError` に変換します。複数項目の取得では成功分を保持し、失敗を件数とerrorで返します。`DownloadPlan.media_url` は内部処理用で、既定repr・公開JSON・履歴へ含めません。

## 移行状態

`src/dler_kun` は旧実装との互換性調査中のコードです。新CLIは `dler_kun2` から起動します。旧パッケージを削除するのは全エンジンの機能・出力比較が済んでからです。
