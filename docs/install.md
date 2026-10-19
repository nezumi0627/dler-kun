# インストール

## 開発 checkout から使う

```powershell
git clone https://github.com/nezumi0627/dler-kun.git
cd dler-kun
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
dler-kun --help
```

macOS / Linux では仮想環境を `source .venv/bin/activate` で有効にします。`dler-kun2` の配布物が、既存の `dler-kun` コマンド名を新しい `dler_kun2` CLI に割り当てます。

## 開発依存

```powershell
python -m pip install -e ".[dev,browser]"
```

開発依存とブラウザ機能には Ruff、basedpyright、pytest、websockets が含まれます。`mixixxx` の HLS 結合には別途 ffmpeg が必要です。

## インストール確認

```powershell
dler-kun --help
dler-kun sites --json
```

`python -m dler_kun2` でも同じCLIを起動できます。
