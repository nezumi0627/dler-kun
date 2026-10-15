"""Verified default listing roots and explicit section aliases."""

BASE = "https://www.85po.net/ja"
DEFAULT_SEEDS = (f"{BASE}/latest-updates/", "https://www.85po.net/vi/latest-updates/")
ALIASES = {
    "latest-updates": (f"{BASE}/latest-updates/",),
    "home": (f"{BASE}/",),
    "top-rated": (f"{BASE}/top-rated/",),
    "most-popular": (f"{BASE}/most-popular/",),
    "tags": (f"{BASE}/tags/",),
    "members": (f"{BASE}/members/",),
    "member-629": (f"{BASE}/members/629/",),
    "member-629-videos": (f"{BASE}/members/629/videos/",),
    "member-629-friends": (f"{BASE}/members/629/friends/",),
    "member-629-favorites": (f"{BASE}/members/629/favorites/videos/",),
}


def resolve_seeds(seeds: tuple[str, ...], options) -> tuple[str, ...]:
    aliases = options.get("sources")
    if isinstance(aliases, str):
        aliases = (aliases,)
    candidates = tuple(
        ALIASES.get(str(alias).lower(), (str(alias),) if str(alias).startswith("https://") else ())
        for alias in aliases
    ) if isinstance(aliases, (list, tuple)) else ()
    flattened = tuple(url for group in candidates for url in group)
    seed_urls = tuple(
        url
        for seed in seeds
        for url in ALIASES.get(str(seed).lower(), (str(seed),) if str(seed).startswith("https://") else ())
    )
    chosen = flattened or seed_urls or DEFAULT_SEEDS
    return tuple(dict.fromkeys(chosen))
