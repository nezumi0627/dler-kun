from typing import Any

import aiohttp

from .go_file_api_manager import GoFileAPIManager

_WT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/136.0.0.0 Safari/537.36"
)


class GofileAccountManager:
    """Gofile.ioのアカウント情報を管理するクラス"""

    def __init__(self, api_server: str = "api"):
        """初期化"""
        self.api_server = api_server
        self._accounts: dict[str, dict[str, Any]] = {}
        self._api_manager = GoFileAPIManager()

    async def fetch_account(self, token: str | None = None) -> dict[str, Any]:
        """/accounts/website からゲストアカウント情報を取得

        Returns:
            Dict[str, Any]: アカウント情報

        Example:
            {
                'id': '4a3d5926-b94c-4d4c-948e-cd9dd5e466e3',
                'createTime': 1741770646,
                'email': 'guest5212037279@gofile.io',
                'tier': 'guest',
                'token': 'nH8oAZ2ibJg8SnBqoWpV2kSG6vaYCYa5',
                ...
            }
        """
        try:
            headers = {
                "User-Agent": _WT_USER_AGENT,
                "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
            }
            if token:
                headers["Authorization"] = f"Bearer {token}"

            async with aiohttp.ClientSession() as session:
                response = await session.get(
                    f"https://{self.api_server}.gofile.io/accounts/website",
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=10),
                )
                response.raise_for_status()
                data = await response.json()
                return data.get("data", {})
        except aiohttp.ClientError as e:
            raise ValueError(f"Failed to fetch account: {e}") from e

    async def sync_account(self, token: str | None = None) -> dict[str, Any]:
        """アカウント情報を取得して同期する"""
        account_data = await self.fetch_account(token)
        self._accounts[account_data["email"]] = account_data
        return account_data

    async def get_account_status(self, token: str | None = None) -> dict[str, Any]:
        """アカウント情報を取得（tokenは後方互換のために残す）"""
        await self.sync_account()
        return await self.get_first_active_account()

    async def get_first_active_account(self) -> dict[str, Any]:
        """最初のアクティブなアカウントを取得"""
        if not self._accounts:
            raise ValueError("No accounts available.")

        active_account = next(
            (
                account
                for account in self._accounts.values()
                if account.get("clientActive")
            ),
            None,
        )

        if not active_account:
            active_account = list(self._accounts.values())[0]
            active_account["clientActive"] = True

        return active_account
