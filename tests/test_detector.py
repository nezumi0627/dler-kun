from dler_kun.detector import ServiceDetector


def test_cdn_twimg1_url_routes_to_mvfile() -> None:
    assert ServiceDetector().detect("https://cdn.twimg1.com/vl99FP") == "mvfile"


def test_related_fun800_domains_route_to_mvfile() -> None:
    detector = ServiceDetector()
    for url in (
        "https://twimg1.com/4qzVgu",
        "https://video1.twimg-album.com/3Mrk3T",
        "https://video.file-bio.com/bKxq6I",
        "https://cdn.twfiles.com/d89Ku3",
        "https://gofile.video/NCrGb9",
        "https://gofile.trade/N7NNfl",
        "https://gofile.bar/d/cs5AeP",
    ):
        assert detector.detect(url) == "mvfile"


def test_linkex_url_routes_to_linkex() -> None:
    assert ServiceDetector().detect("https://l2e.click/i/dV7eZfj") == "linkex"
