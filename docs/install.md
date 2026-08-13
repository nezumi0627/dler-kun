# インストール詳細

## 開発用依存

```bash
pip install -e ".[dev]"   # ruff（リント）
```

## どこからでも使えるようにする（PATH 登録）

venv の `dler-kun.exe` を PATH に通せば、**cmd / PowerShell / bash のどこからでも** `dler-kun` と打てます。

1. シムを置くディレクトリを作り、`dler-kun.cmd`（cmd 用）と `dler-kun`（bash 用）を配置。`<プロジェクトのパス>` はインストール先に置き換える:

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
