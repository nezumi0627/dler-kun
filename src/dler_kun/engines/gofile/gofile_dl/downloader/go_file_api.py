"""
GoFile API client
ソースコード (source/dist/js/) を参照して実装:
  - wt.obf.js          : generateWT のアルゴリズム（ソルト含む）
  - account.js         : getAccountActive / getAccountByTokenAndSync
  - filemanager/api.js : getContent のヘッダー仕様

IP ブロック回避:
  環境変数 GOFILE_LOCAL_ADDR にバインドしたいローカルIPを指定すると
  そのNICからリクエストを送出する。
  例: iPhone USB テザリングのIP
    $env:GOFILE_LOCAL_ADDR = "172.20.10.2"

  またはプロキシを使う場合は GOFILE_PROXY に指定:
    $env:GOFILE_PROXY = "http://127.0.0.1:8080"
    $env:GOFILE_PROXY = "socks5://127.0.0.1:1080"  (要 aiohttp-socks)
"""

import asyncio
import hashlib
import math
import os
import time
import urllib.parse
from typing import Any

import aiohttp

# ── generateWT 定数 (source/dist/js/wt.obf.js より) ──────────────────────
_WT_SALT = "9844d94d963d30"
_WT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/149.0.0.0 Safari/537.36"
)
_WT_LANGUAGE = "ja"
_WT_SEC_CH_UA = '"Google Chrome";v="149", "Chromium";v="149", "Not)A;Brand";v="24"'
_WT_SEC_CH_UA_MOBILE = "?0"
_WT_SEC_CH_UA_PLATFORM = '"Windows"'

# ── rate limit 設定 ────────────────────────────────────────────────────────
_ACCOUNTS_WEBSITE_RETRY_WAIT = 1.0
_ACCOUNTS_WEBSITE_MAX_RETRY = 2


def _get_local_addr() -> str | None:
    """バインドするローカルIPを環境変数から取得。"""
    return os.environ.get("GOFILE_LOCAL_ADDR") or None


def _get_proxy() -> str | None:
    return os.environ.get("GOFILE_PROXY") or None


def _make_connector(
    local_addr: str | None,
    proxy: str | None,
) -> aiohttp.BaseConnector:
    """
    local_addr が指定された場合は TCPConnector(local_addr=...) を使う。
    SOCKS5 プロキシの場合は ProxyConnector を使う（aiohttp-socks 必要）。
    """
    if proxy and proxy.startswith("socks"):
        try:
            from aiohttp_socks import ProxyConnector

            return ProxyConnector.from_url(proxy)
        except ImportError:
            raise ImportError(
                "SOCKS プロキシには aiohttp-socks が必要です: pip install aiohttp-socks"
            )

    if local_addr:
        # local_addr=(IP, 0) でそのNICにバインド
        return aiohttp.TCPConnector(local_addr=(local_addr, 0))

    return aiohttp.TCPConnector()


class GoFileAPI:
    """GoFile API client"""

    API_BASE = "https://api.gofile.io"
    CONTENT_URL = f"{API_BASE}/contents"
    ACCOUNTS_URL = f"{API_BASE}/accounts"
    ACCOUNTS_WEBSITE_URL = f"{API_BASE}/accounts/website"

    SORT_FIELD = "createTime"
    SORT_DIRECTION = "-1"
    PAGE_SIZE = "1000"

    def __init__(
        self,
        session: aiohttp.ClientSession,
        token: str | None = None,
        proxy: str | None = None,
        local_addr: str | None = None,
    ):
        self._session = session
        self._token = token
        self._proxy: str | None = proxy or _get_proxy()
        self._local_addr: str | None = local_addr or _get_local_addr()
        self._cached_account_token: str | None = None

    # ── 内部用セッション（accounts/* への直接呼び出し用） ─────────────────
    def _make_session(self) -> aiohttp.ClientSession:
        connector = _make_connector(self._local_addr, self._proxy)
        return aiohttp.ClientSession(connector=connector)

    def _proxy_arg(self) -> dict[str, Any]:
        """HTTP/HTTPS プロキシ用 kwargs。SOCKS5 は connector 側で処理済み。"""
        if self._proxy and not self._proxy.startswith("socks"):
            return {"proxy": self._proxy}
        return {}

    # ── wt 生成 ────────────────────────────────────────────────────────────
    def _generate_wt(self, account_token: str) -> str:
        timeblock = str(math.floor(time.time() / 14400))
        raw = (
            _WT_USER_AGENT
            + "::"
            + _WT_LANGUAGE
            + "::"
            + account_token
            + "::"
            + timeblock
            + "::"
            + _WT_SALT
        )
        return hashlib.sha256(raw.encode()).hexdigest()

    # ── accounts/website ───────────────────────────────────────────────────
    async def _fetch_account_token_from_website(self, token: str) -> str | None:
        headers = {
            "Authorization": f"Bearer {token}",
            "User-Agent": _WT_USER_AGENT,
            "Accept": "*/*",
            "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
            "Origin": "https://gofile.io",
            "Referer": "https://gofile.io/",
            "sec-ch-ua": _WT_SEC_CH_UA,
            "sec-ch-ua-mobile": _WT_SEC_CH_UA_MOBILE,
            "sec-ch-ua-platform": _WT_SEC_CH_UA_PLATFORM,
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-site",
        }
        for attempt in range(_ACCOUNTS_WEBSITE_MAX_RETRY):
            try:
                async with self._make_session() as s:
                    resp = await s.get(
                        self.ACCOUNTS_WEBSITE_URL,
                        headers=headers,
                        timeout=aiohttp.ClientTimeout(total=5),
                        **self._proxy_arg(),
                    )
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get("status") == "ok":
                            return data["data"]["token"]
                        return None
                    if resp.status == 429:
                        if attempt < _ACCOUNTS_WEBSITE_MAX_RETRY - 1:
                            await asyncio.sleep(_ACCOUNTS_WEBSITE_RETRY_WAIT)
                            continue
                        return None
                    return None
            except Exception:
                return None
        return None

    # ── ゲストアカウント作成 ───────────────────────────────────────────────
    async def _create_guest_account(self) -> str | None:
        try:
            async with self._make_session() as s:
                resp = await s.post(
                    self.ACCOUNTS_URL,
                    headers={"User-Agent": _WT_USER_AGENT},
                    timeout=aiohttp.ClientTimeout(total=5),
                    **self._proxy_arg(),
                )
                if resp.status == 200:
                    data = await resp.json()
                    if data.get("status") == "ok":
                        return data["data"]["token"]
            return None
        except Exception:
            return None

    # ── アカウントトークン取得 ─────────────────────────────────────────────
    async def _get_account_token(self) -> str:
        if self._cached_account_token:
            return self._cached_account_token

        if self._token:
            fetched = await self._fetch_account_token_from_website(self._token)
            self._cached_account_token = fetched or self._token
            return self._cached_account_token

        new_token = await self._create_guest_account()
        if new_token:
            self._token = new_token
            self._cached_account_token = new_token
            return new_token

        raise ValueError("GoFile アカウントトークンを取得できませんでした。")

    # ── コンテンツ取得 ─────────────────────────────────────────────────────
    async def fetch_content(
        self,
        content_id: str,
        password: str | None = None,
    ) -> dict[str, Any] | None:
        account_token = await self._get_account_token()
        wt = self._generate_wt(account_token)
        url = self._build_url(content_id, password)
        headers = self._build_headers(wt, account_token)

        # 502/503/504 は一時的なサーバー障害なのでリトライする
        _RETRYABLE = {502, 503, 504}
        last_err: Exception | None = None

        for attempt in range(2):  # 最大 2 回試行 (0, 1)
            if attempt > 0:
                wait = 1.0  # 1秒
                await asyncio.sleep(wait)

            try:
                response = await self._session.get(
                    url, headers=headers, **self._proxy_arg()
                )
                if response.status in _RETRYABLE:
                    last_err = ValueError(
                        f"HTTP エラー {response.status}: サーバー一時障害 (リトライ {attempt + 1}/4)"
                    )
                    continue  # リトライ
                response.raise_for_status()
            except aiohttp.ClientResponseError as e:
                if e.status in _RETRYABLE:
                    last_err = ValueError(
                        f"HTTP エラー {e.status}: {e.message} (リトライ {attempt + 1}/4)"
                    )
                    continue
                if e.status == 401:
                    raise ValueError(
                        "Unauthorized: コンテンツへのアクセス権がありません。"
                    ) from e
                if e.status == 429:
                    raise ValueError(
                        "Rate limited (HTTP 429)。しばらく待ってから再試行してください。"
                    ) from e
                raise ValueError(f"HTTP エラー {e.status}: {e.message}") from e
            except aiohttp.ClientError as e:
                raise ValueError(f"接続エラー: {e}") from e

            data = await response.json()
            status = data.get("status", "")
            if status == "error-rateLimit":
                raise ValueError(
                    "Rate limited (error-rateLimit)。しばらく待ってから再試行してください。"
                )
            if status == "error-notFound":
                raise FileNotFoundError(
                    f"コンテンツが存在しません（削除済みまたは期限切れ）: {content_id}"
                )
            if status not in ("ok",):
                raise ValueError(f"GoFile API エラー: {status}")

            return data["data"]

        # 全リトライ失敗
        raise last_err or ValueError(
            f"fetch_content: 最大リトライ回数に達しました ({content_id})"
        )

    # ── URL 構築 ────────────────────────────────────────────────────────────
    def _build_url(self, content_id: str, password: str | None = None) -> str:
        params: dict[str, str] = {
            "contentFilter": "",
            "page": "1",
            "pageSize": self.PAGE_SIZE,
            "sortField": self.SORT_FIELD,
            "sortDirection": self.SORT_DIRECTION,
        }
        if password:
            params["password"] = self._sha256(password)
        return f"{self.CONTENT_URL}/{content_id}?{urllib.parse.urlencode(params)}"

    # ── ヘッダー構築 ────────────────────────────────────────────────────────
    def _build_headers(self, wt: str, account_token: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {account_token}",
            "X-Website-Token": wt,
            "X-BL": _WT_LANGUAGE,
            "User-Agent": _WT_USER_AGENT,
            "Accept": "*/*",
            "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Origin": "https://gofile.io",
            "Referer": "https://gofile.io/",
            "sec-ch-ua": _WT_SEC_CH_UA,
            "sec-ch-ua-mobile": _WT_SEC_CH_UA_MOBILE,
            "sec-ch-ua-platform": _WT_SEC_CH_UA_PLATFORM,
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-site",
        }

    @staticmethod
    def _sha256(text: str) -> str:
        return hashlib.sha256(text.encode()).hexdigest()
