"""
ranking_dl.py  ─  ランキング・新着サイトから GoFile URL を収集して自動ダウンロード

対応ソース:
  [gofile-douga.com]  (JSON API 直接)
    - /api/rankings?tab=24h&limit=60   ← ランキング Top 60
    - /api/new?limit=60&offset=...     ← 新着 Top 60

  [gofilelab.com]  (Playwright ヘッドレスブラウザ)
    - /ja/newest
    - /ja/dl-ranking
    - /ja/popular-30d

使い方:
    python ranking_dl.py

環境変数:
    GOFILE_LOCAL_ADDR  … iPhone USB テザリング IP (例: 172.20.10.2)
    GOFILE_PROXY       … HTTP/SOCKS5 プロキシ
"""

import asyncio
import json
import os
import re
import socket
from pathlib import Path

import aiohttp
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from gofile_dl.downloader import GoFileDownloader

console = Console()

# ─── 設定 ────────────────────────────────────────────────────────────────────
IPHONE_ADDR: str | None = os.environ.get("GOFILE_LOCAL_ADDR") or "172.20.10.2"
PROXY: str | None = os.environ.get("GOFILE_PROXY") or None
OUTPUT_DIR = "./downloads/rankings"

_CHECK_HOST = "api.gofile.io"
_CHECK_PORT = 443
_CHECK_TIMEOUT = 5.0

SEEN_FILE = Path("./downloads/rankings/.seen_urls.json")

_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/149.0.0.0 Safari/537.36"
)


# ─── NIC 検出 ────────────────────────────────────────────────────────────────
def _can_reach(ip: str, host: str, port: int, timeout: float) -> bool:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.bind((ip, 0))
        s.connect((host, port))
        s.close()
        return True
    except OSError:
        return False


def _detect_local_addr() -> str | None:
    if not IPHONE_ADDR:
        return None
    try:
        t = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        t.bind((IPHONE_ADDR, 0))
        t.close()
    except OSError:
        return None
    return (
        IPHONE_ADDR
        if _can_reach(IPHONE_ADDR, _CHECK_HOST, _CHECK_PORT, _CHECK_TIMEOUT)
        else None
    )


def _make_connector(local_addr: str | None) -> aiohttp.TCPConnector:
    kw: dict = dict(
        limit=0,
        limit_per_host=0,
        ttl_dns_cache=300,
        force_close=False,
        enable_cleanup_closed=True,
    )
    if local_addr:
        kw["local_addr"] = (local_addr, 0)
    return aiohttp.TCPConnector(**kw)


# ─── 既DL済みキャッシュ ──────────────────────────────────────────────────────
def _load_seen() -> set[str]:
    if SEEN_FILE.exists():
        try:
            return set(json.loads(SEEN_FILE.read_text(encoding="utf-8")))
        except Exception:
            pass
    return set()


def _save_seen(seen: set[str]) -> None:
    SEEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    SEEN_FILE.write_text(
        json.dumps(sorted(seen), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# ─── gofile-douga.com  (JSON API) ────────────────────────────────────────────
_DOUGA_BASE = "https://gofile-douga.com"
_DOUGA_HDR = {
    "User-Agent": _BROWSER_UA,
    "Accept": "application/json",
    "Accept-Language": "ja,en-US;q=0.9",
    "Referer": f"{_DOUGA_BASE}/",
}


async def _check_alive_douga(session: aiohttp.ClientSession, content_id: str) -> bool:
    """gofile-douga.comのページから「削除済み」が含まれるか判定する。"""
    url = f"{_DOUGA_BASE}/g/{content_id}?from=new"
    try:
        async with session.get(
            url, headers=_DOUGA_HDR, timeout=aiohttp.ClientTimeout(total=5)
        ) as r:
            if r.status == 200:
                html = await r.text()
                if "削除済み" in html:
                    return False
    except Exception:
        pass
    return True


async def _fetch_douga_api(session: aiohttp.ClientSession, url: str) -> list[str]:
    """gofile-douga の JSON API から gofileUrl を収集して返す。"""
    urls: list[str] = []
    try:
        async with session.get(
            url, headers=_DOUGA_HDR, timeout=aiohttp.ClientTimeout(total=5)
        ) as r:
            if r.status != 200:
                console.print(f"  [red]douga HTTP {r.status}[/] {url}")
                return urls
            data = await r.json(content_type=None)
        for item in data.get("items", []):
            gurl = item.get("gofileUrl") or ""
            if gurl:
                urls.append(gurl)
    except Exception as e:
        console.print(f"  [red]douga error:[/] {e}")
    return urls


async def scrape_douga(limit: int = 60) -> list[str]:
    """
    gofile-douga.com から:
      - ランキング Top {limit}  (/api/rankings?tab=24h)
      - 新着        Top {limit}  (/api/new)
    を取得して重複なしリストを返す。
    """
    sources = [
        ("ランキング", f"{_DOUGA_BASE}/api/rankings?tab=24h&limit={limit}"),
        ("新着", f"{_DOUGA_BASE}/api/new?limit={limit}"),
    ]

    all_urls: list[str] = []
    seen_local: set[str] = set()

    connector = aiohttp.TCPConnector()
    async with aiohttp.ClientSession(connector=connector) as s:
        for label, url in sources:
            fetched = await _fetch_douga_api(s, url)
            added = 0
            for u in fetched:
                if u not in seen_local:
                    seen_local.add(u)
                    all_urls.append(u)
                    added += 1
            console.print(f"  [cyan]gofile-douga[/] {label}: [bold]{added}[/] 件")

    return all_urls


# ─── gofilelab.com  (Playwright) ─────────────────────────────────────────────
_GOFILELAB_PAGES = [
    ("newest", "https://gofilelab.com/ja/newest"),
    ("dl-ranking", "https://gofilelab.com/ja/dl-ranking"),
    ("popular-30d", "https://gofilelab.com/ja/popular-30d"),
]
_GF_ID_RE = re.compile(r"gofile\.io/d/([A-Za-z0-9]+)")


async def scrape_gofilelab() -> list[str]:
    """
    gofilelab.com を Playwright で開き、gofile.io/d/ URL を収集する。
    年齢確認 Cookie を事前にセットして確認画面をスキップする。
    各ページで「もっと見る」を最大 5 回クリックして追加読み込みする。
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        console.print(
            "  [red]playwright 未インストール。[/] pip install playwright && playwright install chromium"
        )
        return []

    all_urls: list[str] = []
    seen_local: set[str] = set()

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx = await browser.new_context(
            user_agent=_BROWSER_UA,
            locale="ja-JP",
            extra_http_headers={"Accept-Language": "ja,en-US;q=0.9"},
        )
        # 年齢確認 Cookie を先行セット
        await ctx.add_cookies(
            [
                {
                    "name": "age_verified",
                    "value": "true",
                    "domain": "gofilelab.com",
                    "path": "/",
                },
                {
                    "name": "ageVerified",
                    "value": "1",
                    "domain": "gofilelab.com",
                    "path": "/",
                },
                {
                    "name": "age_confirmed",
                    "value": "true",
                    "domain": "gofilelab.com",
                    "path": "/",
                },
            ]
        )

        for label, url in _GOFILELAB_PAGES:
            page = await ctx.new_page()
            added = 0
            try:
                await page.goto(url, wait_until="networkidle", timeout=10_000)

                # 年齢確認ダイアログが残っていたらクリック
                try:
                    btn = page.locator(
                        "button:has-text('同意して閲覧する'), "
                        "button:has-text('同意する'), "
                        "a:has-text('同意して閲覧する')"
                    )
                    if await btn.count() > 0:
                        await btn.first.click()
                        await page.wait_for_load_state("networkidle", timeout=3_000)
                except Exception:
                    pass

                # 「もっと見る」を繰り返しクリック（最大 5 回）
                for _ in range(5):
                    more = page.locator(
                        "button:has-text('もっと見る'), "
                        "a:has-text('もっと見る'), "
                        "button:has-text('Load more'), "
                        "button:has-text('load more')"
                    )
                    if await more.count() == 0:
                        break
                    try:
                        await more.first.click()
                        await page.wait_for_timeout(300)
                    except Exception:
                        break

                content = await page.content()
                for m in _GF_ID_RE.finditer(content):
                    gid = f"https://gofile.io/d/{m.group(1)}"
                    if gid not in seen_local:
                        seen_local.add(gid)
                        all_urls.append(gid)
                        added += 1

            except Exception as e:
                console.print(f"  [red]gofilelab error[/] {label}: {e}")
            finally:
                await page.close()

            console.print(f"  [magenta]gofilelab[/] {label}: [bold]{added}[/] 件")

        await browser.close()

    return all_urls


# ─── メイン ──────────────────────────────────────────────────────────────────
async def main() -> None:
    console.print(
        Panel(
            Text("GoFile Ranking Downloader", style="bold magenta"),
            border_style="bright_blue",
            padding=(0, 2),
        )
    )

    local_addr = _detect_local_addr()
    nic_label = (
        f"[cyan]iPhone USB tethering[/] [dim]({local_addr})[/]"
        if local_addr
        else "[dim]Default (Wi-Fi / LAN)[/]"
    )
    console.print(f"  [bold green]NIC[/]  {nic_label}\n")

    # ── URL 収集 ────────────────────────────────────────────────────────────
    console.print("[bold yellow]■ URL 収集中...[/]")

    douga_urls = await scrape_douga()
    gofilelab_urls = await scrape_gofilelab()

    # 全ソースを統合・重複排除
    all_unique: list[str] = []
    all_seen: set[str] = set()
    for u in douga_urls + gofilelab_urls:
        if u not in all_seen:
            all_seen.add(u)
            all_unique.append(u)

    console.print(f"\n  [bold]合計 {len(all_unique)} 件[/] (重複除去後)\n")

    if not all_unique:
        console.print("[red]URL が取得できませんでした。[/]")
        return

    # ── 既DL済みフィルタ ───────────────────────────────────────────────────
    seen_dl = _load_seen()
    new_urls = [u for u in all_unique if u not in seen_dl]
    skip_cnt = len(all_unique) - len(new_urls)

    # サマリーテーブル
    tbl = Table.grid(padding=(0, 2))
    tbl.add_row("[dim]取得合計[/]", f"[white]{len(all_unique)}[/]")
    tbl.add_row("[dim]既DL済みスキップ[/]", f"[dim]{skip_cnt}[/]")
    tbl.add_row("[bold green]新規DL対象[/]", f"[bold green]{len(new_urls)}[/]")
    console.print(tbl)
    console.print()

    if not new_urls:
        console.print(
            Panel(
                "[bold green]✔ すべて最新です。新規DL対象なし。[/]",
                border_style="green",
            )
        )
        return

    # ── ダウンロード ────────────────────────────────────────────────────────
    console.print("[bold yellow]■ ダウンロード中...[/]\n")

    if PROXY and PROXY.startswith("socks"):
        from aiohttp_socks import ProxyConnector

        connector = ProxyConnector.from_url(PROXY)
    else:
        connector = _make_connector(local_addr)

    timeout = aiohttp.ClientTimeout(
        total=None, connect=30, sock_connect=30, sock_read=60
    )

    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        downloader = GoFileDownloader(session, proxy=PROXY, local_addr=local_addr)
        await downloader.init()

        failed: list[str] = []
        not_found_cnt = 0
        consecutive_fail = 0  # 連続失敗カウンタ

        for i, url in enumerate(new_urls, 1):
            console.print(f"[dim]({i}/{len(new_urls)})[/] [cyan]{url}[/]")

            content_id = url.split("/")[-1]
            is_alive = await _check_alive_douga(session, content_id)
            if not is_alive:
                console.print(
                    "  [dim]⊘ gofile-dougaで「削除済み」を確認 → スキップ記録[/]"
                )
                seen_dl.add(url)
                _save_seen(seen_dl)
                not_found_cnt += 1
                continue

            result = await downloader.download(url, output_dir=OUTPUT_DIR)

            if result["status"] == "not_found":
                console.print("  [dim]⊘ 削除済み・期限切れ → スキップ記録[/]")
                seen_dl.add(url)  # 次回以降スキップ
                _save_seen(seen_dl)
                consecutive_fail = 0
                not_found_cnt += 1
            elif result["status"] == "error":
                msg = result["message"]
                console.print(f"  [red]✗ {msg}[/] → スキップ記録")
                seen_dl.add(url)
                _save_seen(seen_dl)
                failed.append(url)
                consecutive_fail += 1

                # 502/503 系が5回連続したら API 障害とみなして 10 秒待機
                if consecutive_fail >= 5 and (
                    "502" in msg or "503" in msg or "504" in msg
                ):
                    console.print(
                        "  [yellow]⚠ API障害の可能性。10秒待機してから再試行します...[/]"
                    )
                    await asyncio.sleep(10)
                    consecutive_fail = 0
            else:
                consecutive_fail = 0
                seen_dl.add(url)
                _save_seen(seen_dl)

    # ── サマリー ────────────────────────────────────────────────────────────
    ok = len(new_urls) - len(failed) - not_found_cnt
    color = "green" if not failed else "yellow"
    lines = [f"[bold {color}]✔ {ok}/{len(new_urls)} 完了[/]"]
    if not_found_cnt:
        lines.append(f"[dim]⊘ {not_found_cnt} 件 削除済み・スキップ登録[/]")
    if failed:
        lines.append(f"[red]✗ {len(failed)} 失敗 (次回再試行)[/]")
        for f in failed[:5]:
            lines.append(f"  [dim]{f}[/]")
    console.print(Panel("\n".join(lines), title="[bold]Summary", border_style=color))


if __name__ == "__main__":
    asyncio.run(main())
