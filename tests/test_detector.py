from dler_kun.detector import ServiceDetector


def test_detect_known_sites() -> None:
    detector = ServiceDetector()
    assert detector.detect("https://gofile.io/d/abc") == "gofile"
    assert detector.detect("https://85xo.com/v/1/x/") == "85xo"
    assert detector.detect("https://mixi-xxx.cc/scvp-20849/") == "mixixxx"
    assert detector.detect("https://mvfile.com/x") == "mvfile"
    assert detector.detect("https://cdn.tweetfile.com/oNWQL8") == "mvfile"
    assert detector.detect("https://gofile.website/Kf7Ulr") == "mvfile"
    assert detector.detect("https://cdn2.image-share.cc/0u7C9g") == "mvfile"
    assert detector.detect("https://gofile.run/x") == "gofilerun"
    assert detector.detect("https://videy.co/x") == "videy"


def test_detect_unknown_and_edge_cases() -> None:
    detector = ServiceDetector()
    assert detector.detect("https://example.com/") is None
    assert detector.detect("") is None
    assert detector.detect("not a url") is None
    # subdomain matching
    assert detector.detect("https://sub.85xo.com/x") == "85xo"


def test_supported_domains() -> None:
    detector = ServiceDetector()
    domains = detector.supported_domains()
    assert "85xo" in domains
    assert "mixixxx" in domains
    assert "mixi-xxx.cc" in domains["mixixxx"]
