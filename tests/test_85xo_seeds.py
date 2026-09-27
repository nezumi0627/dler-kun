import importlib

from dler_kun import net

seeds = importlib.import_module("dler_kun.engines.85xo.seeds")


def test_default_85xo_seeds_use_current_host() -> None:
    assert all("85po.net" in url for url in seeds.DEFAULT_85XO_SEEDS)
    assert "85po.net" in seeds.expand_85xo_aliases(["latest-updates"])[0]


def test_85po_tls_uses_cloudflare_edge_fallback() -> None:
    assert net.resolve_ipv4("www.85po.net") == (
        "172.67.197.42",
        "104.21.76.154",
    )
