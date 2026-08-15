import json
import os


class TokenFileManager:
    """トークンファイルを管理するクラス"""

    def __init__(self, token_file: str = os.getenv("TOKEN_FILE_PATH", "tokens.json")):
        self.token_file_path = token_file

    def load_tokens(self) -> list[dict[str, str]]:
        """tokens.json からトークンリストを読み込む"""
        try:
            with open(self.token_file_path) as f:
                data = json.load(f)
                return data.get("tokens", [])
        except (FileNotFoundError, json.JSONDecodeError):
            return []

    async def save_tokens(self, tokens: list[dict[str, str]]) -> None:
        """トークンリストを tokens.json に保存"""
        data = {"tokens": tokens}
        with open(self.token_file_path, "w") as f:
            json.dump(data, f, indent=4)
