import aiohttp


class GoFileAPIManager:
    """GoFile APIとの通信を管理するクラス"""

    API_BASE = "https://api.gofile.io"
    ACCOUNT_URL = f"{API_BASE}/accounts"

    async def fetch_new_token(self) -> str:
        """GoFile APIから新しいトークンを取得し返す"""
        async with aiohttp.ClientSession() as session, session.post(
            self.ACCOUNT_URL
        ) as response:
            data = await response.json()
            if response.status != 200:
                raise RuntimeError(
                    f"アカウント作成に失敗しました: HTTP {response.status}"
                )

            if data.get("status") != "ok":
                raise RuntimeError(
                    "アカウント作成に失敗しました: "
                    f"{data.get('message', 'Unknown error')}"
                )

            return data["data"]["token"]
