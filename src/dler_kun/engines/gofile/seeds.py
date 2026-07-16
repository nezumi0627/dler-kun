from __future__ import annotations

_DOUGA_SEEDS: tuple[str, ...] = (
    "https://gofile-douga.com/new",
    "https://gofile-douga.com/",
    "https://gofile-douga.com/?sort=24h",
    "https://gofile-douga.com/?sort=3days",
)

_LAB_SEEDS: tuple[str, ...] = (
    "https://gofilelab.com/ja/popular-24h",
    "https://gofilelab.com/ja/popular-30d",
    "https://gofilelab.com/ja/newest",
    "https://gofilelab.com/ja/dl-ranking",
)

DEFAULT_GOFILE_RANKING_SEEDS: tuple[str, ...] = _DOUGA_SEEDS + _LAB_SEEDS

_SOURCE_ALIASES: dict[str, tuple[str, ...]] = {
    "douga": _DOUGA_SEEDS,
    "gofile-douga": _DOUGA_SEEDS,
    "lab": _LAB_SEEDS,
    "gofilelab": _LAB_SEEDS,
    "new": ("https://gofile-douga.com/new",),
    "home": ("https://gofile-douga.com/",),
    "24h": (
        "https://gofile-douga.com/?sort=24h",
        "https://gofilelab.com/ja/popular-24h",
    ),
    "3days": ("https://gofile-douga.com/?sort=3days",),
    "popular-24h": ("https://gofilelab.com/ja/popular-24h",),
    "popular-30d": ("https://gofilelab.com/ja/popular-30d",),
    "newest": ("https://gofilelab.com/ja/newest",),
    "dl-ranking": ("https://gofilelab.com/ja/dl-ranking",),
}


def expand_source_aliases(sources: list[str] | None) -> list[str]:
    """Map aliases (douga, lab, new, 24h, 3days, home, popular-24h, ...) to seed URLs."""
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

        if key in DEFAULT_GOFILE_RANKING_SEEDS or key.startswith("http"):
            if key not in seen:
                seen.add(key)
                resolved.append(key)

    return resolved


def classify_ranking_seed(seed: str) -> str | None:
    """Return 'douga' or 'lab' or None."""
    normalized = str(seed).strip().lower()
    if not normalized:
        return None
    if "gofile-douga.com" in normalized:
        return "douga"
    if "gofilelab.com" in normalized:
        return "lab"
    return None


def _coerce_seed_list(values: list[str]) -> list[str]:
    """Expand aliases (lab, douga, newest, ...) into concrete ranking URLs."""
    cleaned = [str(value).strip() for value in values if str(value).strip()]
    if not cleaned:
        return []
    expanded = expand_source_aliases(cleaned)
    return expanded if expanded else cleaned


def resolve_gofile_ranking_seeds(
    seeds: list[str] | None = None,
    option_seed: str | None = None,
    config_seeds: list[str] | str | None = None,
    sources: list[str] | None = None,
) -> list[str]:
    """Return concrete seed URLs. Empty input → DEFAULT_GOFILE_RANKING_SEEDS."""
    if seeds:
        resolved = _coerce_seed_list(list(seeds))
        if resolved:
            return resolved

    if option_seed and str(option_seed).strip():
        resolved = _coerce_seed_list([str(option_seed).strip()])
        if resolved:
            return resolved

    if isinstance(config_seeds, str):
        resolved = _coerce_seed_list([config_seeds])
        if resolved:
            return resolved

    if config_seeds:
        resolved = _coerce_seed_list([str(seed) for seed in config_seeds])
        if resolved:
            return resolved

    expanded = expand_source_aliases(sources)
    if expanded:
        return expanded

    return list(DEFAULT_GOFILE_RANKING_SEEDS)
