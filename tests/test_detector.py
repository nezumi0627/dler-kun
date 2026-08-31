from dler_kun.detector import ServiceDetector


def test_cdn_twimg1_url_routes_to_mvfile() -> None:
    assert ServiceDetector().detect("https://cdn.twimg1.com/vl99FP") == "mvfile"
