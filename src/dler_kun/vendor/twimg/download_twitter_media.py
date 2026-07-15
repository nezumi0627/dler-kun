#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
twimg_dl.py — Twitter / tweetfile media downloader

Supports: tweetfile.com, twimg-media.com
Uses ECDH + AES-GCM encrypted API + Caesar-shift URL routing.
Tracks all downloads in a SQLite database (twimg.db).

Usage:
    python download_twitter_media.py <URL> [URL ...] [options]
"""

from __future__ import annotations

import argparse
import base64
import concurrent.futures
import datetime
import json
import logging
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ── Optional dependency bootstrap ─────────────────────────────────────────────
try:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "cryptography"])
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM


# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


# ── Constants ─────────────────────────────────────────────────────────────────
_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
_ALPHA_LEN = len(_ALPHABET)
_ALPHA_INDEX: dict[str, int] = {c: i for i, c in enumerate(_ALPHABET)}

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

_MEDIA_RE = re.compile(r"\.(mp4|m3u8)(\?|$)", re.IGNORECASE)
_URL_RE = re.compile(r"https?://")
_NUXT_RE = re.compile(
    r'<script[^>]*id=["\']__NUXT_DATA__["\'][^>]*>(.*?)</script>', re.S
)
_COVER_RE = re.compile(r"(https://[^/]+/[0-9a-f\-]{36})/thumbnail")
_SAFE_NAME_RE = re.compile(r'[\\/:*?"<>|.]')
_LEADING_A_RE = re.compile(r"^a[A-Za-z0-9]")
_TRAILING_JUNK_RE = re.compile(r"[\s.]+$")

_MEDIA_KEYS = {"fileurl", "originurl", "videourl"}
_VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".flv", ".webm"}

_EP_INIT = "/4790d2ecfa"
_EP_INFO = "/8f237a629a"
_EP_LIST = "/320fb0b134"
_TWEETFILE_EP_INIT = "/2ba99883f8"
_TWEETFILE_EP_INFO = "/0a6bd15c3e"
_TWEETFILE_EP_LIST = "/639aeedd6c"

_SITE_CONFIGS: dict[str, dict] = {
    "twimg-media.com": {
        "ep_init": _EP_INIT,
        "ep_info": _EP_INFO,
        "ep_list": _EP_LIST,
        "skip_tokens": {"mpkvjzy", "2hufcu", "zmttw"},
        "api_domain_keyword": "twimg-media.com",
    },
    "tweetfile.com": {
        "ep_init": _TWEETFILE_EP_INIT,
        "ep_info": _TWEETFILE_EP_INFO,
        "ep_list": _TWEETFILE_EP_LIST,
        "skip_tokens": {"1em1qdc", "ncxjga", "0kv85xqy"},
        "api_domain_keyword": "tweetfile.com",
    },
}

_MIN_VALID_FILE_BYTES = 1024
_DB_LOCK = threading.Lock()


# ══════════════════════════════════════════════════════════════════════════════
# ── Database layer ────────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

_SCHEMA = """
CREATE TABLE IF NOT EXISTS channels (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    page_url    TEXT    NOT NULL UNIQUE,
    link_id     TEXT    NOT NULL,
    site_domain TEXT    NOT NULL,
    first_seen  TEXT    NOT NULL,
    last_seen   TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS files (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id   INTEGER NOT NULL REFERENCES channels(id),
    name         TEXT    NOT NULL,
    video_url    TEXT    NOT NULL,
    folder_path  TEXT    NOT NULL DEFAULT '',
    dest_path    TEXT,
    file_size    INTEGER,
    status       TEXT    NOT NULL DEFAULT 'pending',
    error_msg    TEXT,
    created_at   TEXT    NOT NULL,
    updated_at   TEXT    NOT NULL,
    UNIQUE(channel_id, video_url)
);

CREATE TABLE IF NOT EXISTS runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at  TEXT    NOT NULL,
    finished_at TEXT,
    output_dir  TEXT    NOT NULL,
    total       INTEGER DEFAULT 0,
    ok          INTEGER DEFAULT 0,
    skipped     INTEGER DEFAULT 0,
    failed      INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_files_status    ON files(status);
CREATE INDEX IF NOT EXISTS idx_files_channel   ON files(channel_id);
CREATE INDEX IF NOT EXISTS idx_files_dest_path ON files(dest_path);
"""

# status values:  pending | downloading | ok | skipped | error


class DB:
    """Thread-safe SQLite wrapper. One connection per thread via threading.local."""

    def __init__(self, path: Path) -> None:
        self._path = str(path)
        self._local = threading.local()
        # initialise schema on main thread
        self._conn().executescript(_SCHEMA)
        self._conn().commit()

    def _conn(self) -> sqlite3.Connection:
        if not getattr(self._local, "conn", None):
            conn = sqlite3.connect(self._path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            self._local.conn = conn
        return self._local.conn

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        with _DB_LOCK:
            cur = self._conn().execute(sql, params)
            self._conn().commit()
            return cur

    def fetchone(self, sql: str, params: tuple = ()) -> sqlite3.Row | None:
        return self._conn().execute(sql, params).fetchone()

    def fetchall(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        return self._conn().execute(sql, params).fetchall()

    # ── high-level helpers ────────────────────────────────────────────────────

    def upsert_channel(self, page_url: str, link_id: str, site_domain: str) -> int:
        now = _now()
        row = self.fetchone("SELECT id FROM channels WHERE page_url=?", (page_url,))
        if row:
            self.execute(
                "UPDATE channels SET last_seen=?, link_id=? WHERE id=?",
                (now, link_id, row["id"]),
            )
            return row["id"]
        cur = self.execute(
            "INSERT INTO channels(page_url,link_id,site_domain,first_seen,last_seen) VALUES(?,?,?,?,?)",
            (page_url, link_id, site_domain, now, now),
        )
        return cur.lastrowid  # type: ignore[return-value]

    def upsert_file(
        self,
        channel_id: int,
        name: str,
        video_url: str,
        folder_path: str,
    ) -> int:
        """Insert or return existing file row. Returns row id."""
        now = _now()
        row = self.fetchone(
            "SELECT id, status FROM files WHERE channel_id=? AND video_url=?",
            (channel_id, video_url),
        )
        if row:
            return row["id"]
        cur = self.execute(
            """INSERT INTO files(channel_id,name,video_url,folder_path,status,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?)""",
            (channel_id, name, video_url, folder_path, "pending", now, now),
        )
        return cur.lastrowid  # type: ignore[return-value]

    def set_file_status(
        self,
        file_id: int,
        status: str,
        dest_path: str | None = None,
        file_size: int | None = None,
        error_msg: str | None = None,
    ) -> None:
        self.execute(
            """UPDATE files
               SET status=?, dest_path=?, file_size=?, error_msg=?, updated_at=?
               WHERE id=?""",
            (status, dest_path, file_size, error_msg, _now(), file_id),
        )

    def is_already_ok(self, channel_id: int, video_url: str) -> tuple[bool, str | None]:
        """Returns (already_done, dest_path)."""
        row = self.fetchone(
            "SELECT status, dest_path FROM files WHERE channel_id=? AND video_url=?",
            (channel_id, video_url),
        )
        if row and row["status"] == "ok":
            return True, row["dest_path"]
        return False, None

    def start_run(self, output_dir: str) -> int:
        cur = self.execute(
            "INSERT INTO runs(started_at, output_dir) VALUES(?,?)",
            (_now(), output_dir),
        )
        return cur.lastrowid  # type: ignore[return-value]

    def finish_run(self, run_id: int, ok: int, skipped: int, failed: int) -> None:
        total = ok + skipped + failed
        self.execute(
            "UPDATE runs SET finished_at=?,total=?,ok=?,skipped=?,failed=? WHERE id=?",
            (_now(), total, ok, skipped, failed, run_id),
        )

    # ── summary / query helpers ───────────────────────────────────────────────

    def summary(self) -> dict:
        rows = self.fetchall(
            """SELECT status, COUNT(*) AS cnt FROM files GROUP BY status"""
        )
        counts = {r["status"]: r["cnt"] for r in rows}
        ch = self.fetchone("SELECT COUNT(*) AS cnt FROM channels")["cnt"]  # type: ignore[index]
        runs = self.fetchone("SELECT COUNT(*) AS cnt FROM runs")["cnt"]  # type: ignore[index]
        return {
            "channels": ch,
            "runs": runs,
            "files_ok": counts.get("ok", 0),
            "files_skipped": counts.get("skipped", 0),
            "files_error": counts.get("error", 0),
            "files_pending": counts.get("pending", 0),
        }

    def failed_files(self) -> list[sqlite3.Row]:
        return self.fetchall(
            """SELECT f.name, f.video_url, f.error_msg, c.page_url
               FROM files f JOIN channels c ON c.id=f.channel_id
               WHERE f.status='error'
               ORDER BY f.updated_at DESC"""
        )

    def channel_files(self, page_url: str) -> list[sqlite3.Row]:
        return self.fetchall(
            """SELECT f.name, f.status, f.dest_path, f.file_size, f.error_msg
               FROM files f JOIN channels c ON c.id=f.channel_id
               WHERE c.page_url=?
               ORDER BY f.folder_path, f.name""",
            (page_url,),
        )


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


# ══════════════════════════════════════════════════════════════════════════════
# ── HTTP session ──────────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════


def _make_session(retries: int = 3, backoff: float = 0.3) -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=retries,
        backoff_factor=backoff,
        status_forcelist={429, 500, 502, 503, 504},
        allowed_methods={"GET", "POST"},
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=64, pool_maxsize=128)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update({"User-Agent": _USER_AGENT, "Accept": "*/*"})
    return session


_SESSION = _make_session()


# ══════════════════════════════════════════════════════════════════════════════
# ── Caesar-shift + domain helpers ─────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════


def _domain_seed(domain: str) -> int:
    h = 5381
    for ch in domain:
        h = ((h << 5) + h + ord(ch)) & 0xFFFF_FFFF
    return (h % (_ALPHA_LEN - 1)) + 1


def _caesar(path: str, shift: int) -> str:
    return "".join(
        _ALPHABET[(_ALPHA_INDEX[c] + shift) % _ALPHA_LEN] if c in _ALPHA_INDEX else c
        for c in path
    )


def _main_domain(hostname: str) -> str:
    parts = hostname.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else hostname


# ══════════════════════════════════════════════════════════════════════════════
# ── Page config extraction ────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class PageConfig:
    api_domain: str
    link_id: str
    site_domain: str
    ep_init: str = _EP_INIT
    ep_info: str = _EP_INFO
    ep_list: str = _EP_LIST


def _find_nested(obj: object, key: str, depth: int = 0) -> str | None:
    if depth > 20:
        return None
    if isinstance(obj, dict):
        if key in obj and isinstance(obj[key], str):
            return obj[key]
        for v in obj.values():
            r = _find_nested(v, key, depth + 1)
            if r:
                return r
    elif isinstance(obj, list):
        for item in obj:
            r = _find_nested(item, key, depth + 1)
            if r:
                return r
    return None


def extract_config(page_url: str) -> PageConfig:
    r = _SESSION.get(page_url, timeout=15)
    r.raise_for_status()

    parsed_url = urlparse(page_url)
    site_domain = _main_domain(parsed_url.netloc)
    site_cfg = _SITE_CONFIGS.get(site_domain, _SITE_CONFIGS["twimg-media.com"])
    skip_tokens = site_cfg["skip_tokens"]
    api_domain_kw = site_cfg["api_domain_keyword"]
    default_ep_init = site_cfg["ep_init"]
    default_ep_info = site_cfg["ep_info"]
    default_ep_list = site_cfg["ep_list"]

    html = r.text

    shield_init_m = re.search(
        r'apiShieldInitPath["\s]*:["\s]*["\']([^"\']+)["\']', html
    )
    shield_info_m = re.search(
        r'apiShieldInfoPath["\s]*:["\s]*["\']([^"\']+)["\']', html
    )
    shield_list_m = re.search(
        r'apiShieldListPath["\s]*:["\s]*["\']([^"\']+)["\']', html
    )

    m = _NUXT_RE.search(html)
    if not m:
        raise ValueError("__NUXT_DATA__ block not found.")

    data: list = json.loads(m.group(1).strip())
    strings = [v for v in data if isinstance(v, str)]

    api_domain = next(
        (
            s
            for s in strings
            if s.startswith("https://")
            and api_domain_kw in s
            and "/s/" not in s
            and not s.endswith(".js")
            and not any(k in s for k in skip_tokens)
        ),
        None,
    )
    if not api_domain:
        raise ValueError(f"Could not locate apiDomain for {site_domain}.")

    ep_init = (
        (shield_init_m.group(1) if shield_init_m else None)
        or _find_nested(data, "apiShieldInitPath")
        or default_ep_init
    )
    ep_info = (
        (shield_info_m.group(1) if shield_info_m else None)
        or _find_nested(data, "apiShieldInfoPath")
        or _find_nested(data, "apiShieldGetInfoPath")
        or default_ep_info
    )
    ep_list = (
        (shield_list_m.group(1) if shield_list_m else None)
        or _find_nested(data, "apiShieldListPath")
        or _find_nested(data, "apiShieldGetListPath")
        or default_ep_list
    )

    log.info("Endpoints: init=%s  info=%s  list=%s", ep_init, ep_info, ep_list)

    link_id = page_url.rstrip("/").split("/")[-1]
    for i, v in enumerate(data):
        if v == "$slink-id" and i + 1 < len(data):
            idx = data[i + 1]
            if isinstance(idx, int) and idx < len(data) and isinstance(data[idx], str):
                link_id = data[idx]
                break

    if _LEADING_A_RE.match(link_id):
        link_id = link_id[1:]

    return PageConfig(
        api_domain=api_domain,
        link_id=link_id,
        site_domain=site_domain,
        ep_init=ep_init,
        ep_info=ep_info,
        ep_list=ep_list,
    )


# ══════════════════════════════════════════════════════════════════════════════
# ── ECDH + AES-GCM API client ─────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════


@dataclass
class ApiClient:
    api_domain: str
    page_url: str
    site_domain: str = "twimg-media.com"
    ep_init: str = _EP_INIT
    ep_info: str = _EP_INFO
    ep_list: str = _EP_LIST

    _origin: str = field(init=False, repr=False)
    _shift: int = field(init=False, repr=False)
    _session_key: bytes | None = field(default=None, init=False, repr=False)
    _token: str | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        parsed = urlparse(self.page_url)
        self._origin = f"{parsed.scheme}://{parsed.netloc}"
        self._shift = _domain_seed(_main_domain(parsed.netloc))

    def _url(self, path: str) -> str:
        return self.api_domain.rstrip("/") + _caesar(path, self._shift)

    def _headers(self) -> dict[str, str]:
        return {
            "User-Agent": _USER_AGENT,
            "Origin": self._origin,
            "Referer": self.page_url,
            "Content-Type": "text/plain",
        }

    def _assert_ready(self) -> None:
        if not (self._session_key and self._token):
            raise RuntimeError("init_session() must be called first.")

    def _aesgcm(self) -> AESGCM:
        self._assert_ready()
        return AESGCM(self._session_key)  # type: ignore[arg-type]

    def _encrypt(self, payload: dict) -> dict:
        self._assert_ready()
        iv = os.urandom(12)
        ct = self._aesgcm().encrypt(
            iv, json.dumps(payload, separators=(",", ":")).encode(), None
        )
        return {
            "d": base64.b64encode(ct[:-16]).decode(),
            "v": base64.b64encode(iv).decode(),
            "t": base64.b64encode(ct[-16:]).decode(),
            "_tk": self._token,
        }

    def _decrypt(self, enc: dict) -> dict:
        self._assert_ready()
        rd, rv, rt = (base64.b64decode(enc[k]) for k in ("d", "v", "t"))
        return json.loads(self._aesgcm().decrypt(rv, rd + rt, None))

    def init_session(self) -> None:
        priv = ec.generate_private_key(ec.SECP256R1())
        cpk_hex = (
            priv.public_key()
            .public_bytes(
                serialization.Encoding.X962,
                serialization.PublicFormat.UncompressedPoint,
            )
            .hex()
        )
        r = _SESSION.post(
            self._url(self.ep_init),
            data=json.dumps({"cpk": cpk_hex}),
            headers=self._headers(),
            timeout=10,
        )
        r.raise_for_status()
        p = r.json()
        srv_pub = ec.EllipticCurvePublicKey.from_encoded_point(
            ec.SECP256R1(), bytes.fromhex(p["k"])
        )
        shared = priv.exchange(ec.ECDH(), srv_pub)
        digest = hashes.Hash(hashes.SHA256())
        digest.update(shared)
        self._session_key = digest.finalize()
        d, v, t = (base64.b64decode(p[k]) for k in ("d", "v", "t"))
        self._token = json.loads(AESGCM(self._session_key).decrypt(v, d + t, None))[
            "token"
        ]

    def request(
        self,
        path: str,
        method: str = "GET",
        query: dict | None = None,
        body: dict | None = None,
    ) -> dict:
        payload: dict = {
            "q": {k: str(v) for k, v in (query or {}).items()},
            "m": method.upper(),
        }
        if body is not None:
            payload["b"] = body
        r = _SESSION.post(
            self._url(path),
            data=json.dumps(self._encrypt(payload), separators=(",", ":")),
            headers=self._headers(),
            timeout=15,
        )
        r.raise_for_status()
        return self._decrypt(r.json())

    def get_info(self, link_id: str) -> tuple[dict, str]:
        resp = self.request(
            self.ep_info, query={"externalLinks": link_id, "domain": self.site_domain}
        )
        ext = (
            resp.get("data", {})
            .get("info", {})
            .get("extraInfo", {})
            .get("externalLinks", "")
            or ""
        )
        return resp, ext

    def get_list_page(self, ext_links: str, page: int = 1, size: int = 100) -> dict:
        return self.request(
            self.ep_list,
            query={
                "externalLinks": ext_links,
                "pageNo": page,
                "pageSize": size,
                "sortOrder": "2",
            },
        )

    def iter_list(self, ext_links: str, size: int = 100) -> Iterator[dict]:
        page, fetched = 1, 0
        while True:
            resp = self.get_list_page(ext_links, page, size)
            if resp.get("code") != 0:
                log.warning("List API error: %s", resp)
                break
            data = resp.get("data", {})
            items: list[dict] = data.get("list", [])
            total: int = data.get("total", 0)
            yield from items
            fetched += len(items)
            log.info("  Fetched %d / %d", fetched, total)
            if not items or fetched >= total:
                break
            page += 1


# ══════════════════════════════════════════════════════════════════════════════
# ── URL / item helpers ────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════


def _collect_media_urls(obj: object, found: set[str]) -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, str):
                if _URL_RE.search(v) and _MEDIA_RE.search(v):
                    found.add(v)
                elif k.lower() in _MEDIA_KEYS and v.startswith("http"):
                    found.add(v)
            else:
                _collect_media_urls(v, found)
    elif isinstance(obj, list):
        for item in obj:
            _collect_media_urls(item, found)


def _video_urls_from(obj: object) -> set[str]:
    found: set[str] = set()
    _collect_media_urls(obj, found)
    return found


def _cover_to_playlist(cover: str) -> str | None:
    m = _COVER_RE.match(cover)
    return f"{m.group(1)}/playlist.m3u8" if m else None


def _item_video_url(item: dict) -> str | None:
    for key in ("fileUrl", "fileurl", "originUrl", "originurl"):
        val = item.get(key)
        if val and isinstance(val, str) and val.startswith("http"):
            if ".m3u8" in val.lower() or ".mp4" in val.lower():
                return val
    cover = item.get("coverImage", "")
    return _cover_to_playlist(cover) if cover else None


def _safe_name(name: str) -> str:
    cleaned = _SAFE_NAME_RE.sub("_", name)
    return _TRAILING_JUNK_RE.sub("", cleaned) or "_"


# ══════════════════════════════════════════════════════════════════════════════
# ── Download item model ───────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════


@dataclass
class DownloadItem:
    name: str
    video_url: str
    folder_path: str = ""
    db_id: int = 0  # files.id in DB


def _resolve_items(
    client: ApiClient, ext_links: str, current_folder: str = ""
) -> list[DownloadItem]:
    result: list[DownloadItem] = []
    for item in client.iter_list(ext_links):
        name = item.get("name", "untitled")
        landing = item.get("landingPage", "")
        if item.get("isFolder"):
            new_folder = "/".join(filter(None, [current_folder, _safe_name(name)]))
            log.info("📁 %s (%s items)", new_folder, item.get("childrenFileNum", "?"))
            result.extend(_resolve_items(client, landing, new_folder))
        else:
            url = _item_video_url(item)
            if url:
                result.append(
                    DownloadItem(name=name, video_url=url, folder_path=current_folder)
                )
    return result


# ══════════════════════════════════════════════════════════════════════════════
# ── HLS / MP4 download ────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════


def _pick_best_stream(m3u8_url: str, quality: str = "best") -> str:
    r = _SESSION.get(m3u8_url, timeout=15)
    r.raise_for_status()
    text = r.text
    if "#EXT-X-STREAM-INF" not in text:
        return m3u8_url
    base = m3u8_url.rsplit("/", 1)[0]
    streams: list[tuple[int, str]] = []
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if not line.startswith("#EXT-X-STREAM-INF"):
            continue
        bw_m = re.search(r"BANDWIDTH=(\d+)", line)
        bw = int(bw_m.group(1)) if bw_m else 0
        for nxt in lines[i + 1 :]:
            nxt = nxt.strip()
            if nxt and not nxt.startswith("#"):
                streams.append((bw, nxt if nxt.startswith("http") else f"{base}/{nxt}"))
                break
    if not streams:
        return m3u8_url
    streams.sort(key=lambda x: x[0], reverse=(quality == "best"))
    bw, url = streams[0]
    log.info("Selected stream: %d kbps", bw // 1000)
    return url


def _parse_segments(media_url: str) -> list[str]:
    r = _SESSION.get(media_url, timeout=15)
    r.raise_for_status()
    base = media_url.rsplit("/", 1)[0]
    return [
        line if line.startswith("http") else f"{base}/{line}"
        for line in r.text.splitlines()
        if line.strip() and not line.startswith("#")
    ]


def _fetch_segment(args: tuple[int, str]) -> tuple[int, bytes]:
    idx, url = args
    r = _SESSION.get(url, timeout=30)
    r.raise_for_status()
    return idx, r.content


def download_hls(
    m3u8_url: str,
    dest: Path,
    referer: str,
    workers: int = 16,
    quality: str = "best",
    parallel_mode: bool = False,
) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    media_url = _pick_best_stream(m3u8_url, quality)
    segments = _parse_segments(media_url)
    total = len(segments)
    log.info("Downloading %d segments (workers=%d)...", total, workers)

    with tempfile.TemporaryDirectory(prefix="hls_dl_") as tmp:
        tmp_path = Path(tmp)
        seg_paths = [tmp_path / f"seg_{i:05d}.ts" for i in range(total)]
        done_count = 0

        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            futs = {
                pool.submit(_fetch_segment, (i, url)): i
                for i, url in enumerate(segments)
            }
            try:
                for fut in concurrent.futures.as_completed(futs):
                    idx, data = fut.result()
                    seg_paths[idx].write_bytes(data)
                    done_count += 1
                    if not parallel_mode:
                        pct = done_count * 100 // total
                        bar = "█" * (pct // 5) + "░" * (20 - pct // 5)
                        print(
                            f"\r  [{bar}] {pct:3d}%  ({done_count}/{total})",
                            end="",
                            flush=True,
                        )
            except KeyboardInterrupt:
                for f in futs:
                    f.cancel()
                raise
        if not parallel_mode:
            print()

        concat_list = tmp_path / "concat.txt"
        with concat_list.open("w") as f:
            for p in seg_paths:
                f.write(f"file '{p}'\n")

        tmp_mp4 = tmp_path / "output.mp4"
        proc = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat_list),
                "-c",
                "copy",
                str(tmp_mp4),
            ],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            log.error("ffmpeg failed:\n%s", proc.stderr[-800:])
            raise RuntimeError("ffmpeg muxing failed")

        shutil.move(str(tmp_mp4), str(dest))
    log.info("✓ %s  (%.1f MB)", dest.name, dest.stat().st_size / 1024 / 1024)


def download_mp4(url: str, dest: Path, referer: str) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with _SESSION.get(url, headers={"Referer": referer}, stream=True, timeout=60) as r:
        r.raise_for_status()
        with dest.open("wb") as f:
            for chunk in r.iter_content(65536):
                if chunk:
                    f.write(chunk)
    log.info("✓ %s", dest.name)


# ══════════════════════════════════════════════════════════════════════════════
# ── File path helpers ─────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════


def _is_valid_video(path: Path) -> bool:
    return path.exists() and path.stat().st_size >= _MIN_VALID_FILE_BYTES


def _resolve_dest(path: Path, force: bool = False) -> Path | None:
    if not path.exists():
        return path
    if force:
        return path
    if _is_valid_video(path):
        return None  # skip
    stem, suffix = path.stem, path.suffix
    for i in range(1, 10_000):
        candidate = path.with_name(f"{stem}_{i}{suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError("Too many duplicate filenames.")


# ══════════════════════════════════════════════════════════════════════════════
# ── Stats ─────────────────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════


@dataclass
class Stats:
    ok: int = 0
    fail: int = 0
    skip: int = 0

    def __iadd__(self, other: Stats) -> Stats:
        self.ok += other.ok
        self.fail += other.fail
        self.skip += other.skip
        return self


# ══════════════════════════════════════════════════════════════════════════════
# ── Per-URL processing ────────────────────────────────════════════════════════
# ══════════════════════════════════════════════════════════════════════════════


def process_url(
    page_url: str,
    base_dir: Path,
    args: argparse.Namespace,
    db: DB,
) -> Stats:
    stats = Stats()
    log.info("\n%s\nProcessing: %s", "=" * 60, page_url)
    t0 = time.monotonic()

    try:
        config = extract_config(page_url)
        log.info("linkId=%s  apiDomain=%s", config.link_id, config.api_domain)

        channel_id = db.upsert_channel(page_url, config.link_id, config.site_domain)
        out_dir = base_dir / config.link_id
        out_dir.mkdir(parents=True, exist_ok=True)

        client = ApiClient(
            api_domain=config.api_domain,
            page_url=page_url,
            site_domain=config.site_domain,
            ep_init=config.ep_init,
            ep_info=config.ep_info,
            ep_list=config.ep_list,
        )
        client.init_session()

        info_resp, list_ext_links = client.get_info(config.link_id)

        single_urls = _video_urls_from(info_resp)
        main_url = next(
            (u for u in single_urls if ".m3u8" in u.lower()),
            next(iter(single_urls), None),
        )

        dl_items: list[DownloadItem] = []
        if main_url:
            dl_items.append(DownloadItem(name=config.link_id, video_url=main_url))
        if list_ext_links:
            log.info("Collecting list (externalLinks=%s) ...", list_ext_links)
            dl_items.extend(_resolve_items(client, list_ext_links))

        if not dl_items:
            log.warning("No downloadable videos found.")
            return stats

        log.info("Found %d video(s) to download.", len(dl_items))

        # Register all items in DB + build pending list
        pending: list[tuple[DownloadItem, Path]] = []
        for item in dl_items:
            file_id = db.upsert_file(
                channel_id, item.name, item.video_url, item.folder_path
            )
            item.db_id = file_id

            # DB-level duplicate check
            already_ok, saved_path = db.is_already_ok(channel_id, item.video_url)
            if (
                already_ok
                and saved_path
                and Path(saved_path).exists()
                and _is_valid_video(Path(saved_path))
            ):
                log.info("  ⊘ DB skip: %s", item.name)
                db.set_file_status(file_id, "skipped")
                stats.skip += 1
                continue

            safe = _safe_name(item.name)
            dest_dir = (
                (out_dir / _safe_name(item.folder_path))
                if item.folder_path
                else out_dir
            )
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = _resolve_dest(dest_dir / f"{Path(safe).stem}.mp4", force=args.force)

            if dest is None:
                # File exists on disk — mark ok in DB
                existing = dest_dir / f"{Path(safe).stem}.mp4"
                db.set_file_status(
                    file_id,
                    "skipped",
                    dest_path=str(existing),
                    file_size=existing.stat().st_size if existing.exists() else None,
                )
                stats.skip += 1
            else:
                db.set_file_status(file_id, "pending")
                pending.append((item, dest))

        log.info(
            "Queued %d file(s) to download  (skipping %d already complete).",
            len(pending),
            stats.skip,
        )

        # ── download worker ───────────────────────────────────────────────────
        def _download_one(
            item_dest: tuple[DownloadItem, Path], parallel: bool = False
        ) -> tuple[DownloadItem, Path, bool, str]:
            item, dest = item_dest
            db.set_file_status(item.db_id, "downloading")
            try:
                if ".m3u8" in item.video_url.lower():
                    download_hls(
                        item.video_url,
                        dest,
                        page_url,
                        workers=args.seg_workers,
                        quality=args.quality,
                        parallel_mode=parallel,
                    )
                else:
                    download_mp4(item.video_url, dest, page_url)
                size = dest.stat().st_size if dest.exists() else 0
                db.set_file_status(
                    item.db_id, "ok", dest_path=str(dest), file_size=size
                )
                return item, dest, True, ""
            except Exception as exc:
                err = str(exc)
                db.set_file_status(item.db_id, "error", error_msg=err)
                return item, dest, False, err

        vid_workers = getattr(args, "vid_workers", 1)
        if vid_workers > 1:
            with concurrent.futures.ThreadPoolExecutor(max_workers=vid_workers) as pool:
                futs = {
                    pool.submit(_download_one, pair, True): pair[0].name
                    for pair in pending
                }
                for fut in concurrent.futures.as_completed(futs):
                    item, dest, ok, err = fut.result()
                    if ok:
                        log.info("✓ %s", item.name)
                        stats.ok += 1
                    else:
                        log.error("✗ %s: %s", item.name, err)
                        stats.fail += 1
        else:
            for item, dest in pending:
                log.info("→ %s", item.name)
                _, _, ok, err = _download_one((item, dest), False)
                if ok:
                    stats.ok += 1
                else:
                    log.error("✗ %s: %s", item.name, err)
                    stats.fail += 1

    except KeyboardInterrupt:
        raise
    except Exception as exc:
        log.error("Fatal error for %s: %s", page_url, exc)
        stats.fail += 1

    elapsed = time.monotonic() - t0
    log.info(
        "  [%s] done in %.1fs — ✓%d  ✗%d  ⊘%d",
        page_url.split("/")[-1],
        elapsed,
        stats.ok,
        stats.fail,
        stats.skip,
    )
    return stats


# ══════════════════════════════════════════════════════════════════════════════
# ── Summary printer ───────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════


def print_summary(db: DB, base_dir: Path, total: Stats, elapsed: float) -> None:
    sep = "═" * 62
    s = db.summary()
    print(f"\n{sep}")
    print(f"  {'SESSION SUMMARY':^58}")
    print(sep)
    print(f"  Elapsed          {elapsed:.1f}s")
    print(f"  This run  ✓ {total.ok:>5}  succeeded")
    print(f"            ✗ {total.fail:>5}  failed")
    print(f"            ⊘ {total.skip:>5}  skipped")
    print(sep)
    print(f"  {'DATABASE TOTALS':^58}")
    print(sep)
    print(f"  Channels         {s['channels']}")
    print(f"  Files  ok        {s['files_ok']}")
    print(f"         skipped   {s['files_skipped']}")
    print(f"         error     {s['files_error']}")
    print(f"         pending   {s['files_pending']}")
    print(f"  Runs             {s['runs']}")
    print(f"  Output dir       {base_dir}")
    print(f"  DB               {base_dir / 'twimg.db'}")

    failed = db.failed_files()
    if failed:
        print(sep)
        print(f"  {'FAILED FILES':^58}")
        print(sep)
        for row in failed[:20]:
            print(f"  ✗ {row['name'][:50]}")
            print(f"      {row['error_msg'][:80] if row['error_msg'] else ''}")
        if len(failed) > 20:
            print(f"  … and {len(failed) - 20} more (query DB for full list)")
    print(sep)


# ══════════════════════════════════════════════════════════════════════════════
# ── CLI ───────────────────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="twimg_dl",
        description="Download videos from tweetfile / twimg-media pages.",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    p.add_argument("urls", nargs="*", help="Landing page URL(s)")
    p.add_argument(
        "-o",
        "--output-dir",
        default="./videos",
        metavar="DIR",
        help="Output directory  [./videos]",
    )
    p.add_argument(
        "-w",
        "--seg-workers",
        type=int,
        default=16,
        metavar="N",
        dest="seg_workers",
        help="HLS segment threads per video  [16]",
    )
    p.add_argument(
        "-p",
        "--parallel",
        type=int,
        default=3,
        metavar="N",
        dest="vid_workers",
        help="Videos to download in parallel  [3]",
    )
    p.add_argument(
        "-q",
        "--quality",
        choices=["best", "worst"],
        default="best",
        help="HLS quality  [best]",
    )
    p.add_argument(
        "-f", "--force", action="store_true", help="Force overwrite existing files"
    )
    p.add_argument("-v", "--verbose", action="store_true", help="Debug logging")
    p.add_argument(
        "--db-summary",
        action="store_true",
        help="Print DB summary and exit (no download)",
    )
    p.add_argument(
        "--db-failed",
        action="store_true",
        help="List all failed files from DB and exit",
    )
    p.add_argument(
        "--db-channel",
        metavar="URL",
        help="Show all files for a given channel URL and exit",
    )
    return p


def main() -> None:
    args = _build_parser().parse_args()
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    base_dir = Path(args.output_dir).resolve()
    base_dir.mkdir(parents=True, exist_ok=True)
    db = DB(base_dir / "twimg.db")

    # ── DB query modes ────────────────────────────────────────────────────────
    if args.db_summary:
        s = db.summary()
        print(json.dumps(s, indent=2, ensure_ascii=False))
        return

    if args.db_failed:
        rows = db.failed_files()
        if not rows:
            print("No failed files.")
            return
        for row in rows:
            print(f"  ✗ [{row['page_url'].split('/')[-1]}] {row['name']}")
            print(f"      {row['error_msg']}")
        return

    if args.db_channel:
        rows = db.channel_files(args.db_channel)
        if not rows:
            print("Channel not found or no files.")
            return
        for row in rows:
            size_str = (
                f"{row['file_size'] / 1024 / 1024:.1f}MB" if row["file_size"] else "?"
            )
            path_str = row["dest_path"] or "-"
            print(
                f"  [{row['status']:9s}] {row['name']:50s}  {size_str:>8}  {path_str}"
            )
        return

    if not args.urls:
        _build_parser().print_help()
        sys.exit(0)

    # ── Download mode ─────────────────────────────────────────────────────────
    run_id = db.start_run(str(base_dir))
    t0 = time.monotonic()
    total = Stats()

    try:
        for page_url in args.urls:
            total += process_url(page_url.rstrip("/"), base_dir, args, db)
    except KeyboardInterrupt:
        print("\nInterrupted by user.")

    elapsed = time.monotonic() - t0
    db.finish_run(run_id, total.ok, total.skip, total.fail)
    print_summary(db, base_dir, total, elapsed)

    if total.fail:
        sys.exit(1)


if __name__ == "__main__":
    main()
