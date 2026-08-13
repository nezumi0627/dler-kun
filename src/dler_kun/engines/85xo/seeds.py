from __future__ import annotations

_BASE = "https://www.85xo.com/ja"

DEFAULT_85XO_SEEDS: tuple[str, ...] = (
    f"{_BASE}/latest-updates/",
    "https://www.85xo.com/vi/latest-updates/",
)

_SOURCE_ALIASES: dict[str, tuple[str, ...]] = {
    "latest-updates": (f"{_BASE}/latest-updates/",),
    "home": (f"{_BASE}/",),
    "top-rated": (f"{_BASE}/top-rated/",),
    "most-popular": (f"{_BASE}/most-popular/",),
    "tags": (f"{_BASE}/tags/",),
    "members": (f"{_BASE}/members/",),
    "member-629": (f"{_BASE}/members/629/",),
    "member-629-videos": (f"{_BASE}/members/629/videos/",),
    "member-629-friends": (f"{_BASE}/members/629/friends/",),
    "member-629-favorites": (f"{_BASE}/members/629/favorites/videos/",),
}


def expand_85xo_aliases(sources: list[str] | None) -> list[str]:
    """Map section aliases (top-rated, most-popular, tags, home, members, ...) to seed URLs."""
    if not sources:
        return []

    seen: set[str] = set()
    resolved: list[str] = []

    for source in sources:
        key = str(source).strip()
        if not key:
            continue

        alias_key = key.lower()
        mapped = _SOURCE_ALIASES.get(alias_key)
        if mapped:
            for url in mapped:
                if url not in seen:
                    seen.add(url)
                    resolved.append(url)
            continue

        if key in DEFAULT_85XO_SEEDS or key.startswith("http"):
            if key not in seen:
                seen.add(key)
                resolved.append(key)

    return resolved


def resolve_85xo_seeds(
    seeds: list[str] | None = None,
    option_seed: str | None = None,
    config_seeds: list[str] | str | None = None,
    legacy_config_seed: str | None = None,
    sources: list[str] | None = None,
) -> list[str]:
    expanded = expand_85xo_aliases(sources)
    if expanded:
        return expanded

    if seeds:
        cleaned = [str(seed).strip() for seed in seeds if str(seed).strip()]
        if cleaned:
            return cleaned

    if option_seed and str(option_seed).strip():
        return [str(option_seed).strip()]

    if isinstance(config_seeds, str):
        cleaned = [config_seeds.strip()] if config_seeds.strip() else []
        if cleaned:
            return cleaned

    if config_seeds:
        cleaned = [str(seed).strip() for seed in config_seeds if str(seed).strip()]
        if cleaned:
            return cleaned

    if legacy_config_seed and str(legacy_config_seed).strip():
        return [str(legacy_config_seed).strip()]

    return list(DEFAULT_85XO_SEEDS)
