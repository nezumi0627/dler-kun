from __future__ import annotations

DEFAULT_85XO_SEEDS: tuple[str, ...] = (
    "https://www.85xo.com/ja/latest-updates/",
    "https://www.85xo.com/vi/latest-updates/",
)


def resolve_85xo_seeds(
    seeds: list[str] | None = None,
    option_seed: str | None = None,
    config_seeds: list[str] | str | None = None,
    legacy_config_seed: str | None = None,
) -> list[str]:
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
