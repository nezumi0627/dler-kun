from dler_kun.engines.mixixxx.fast import (
    discover_video_pages,
    extract_embed_url,
    extract_video_page_links,
    is_video_page_url,
    listing_page_url,
)


def test_listing_page_url() -> None:
    assert listing_page_url("https://mixi-xxx.cc/", 1) == "https://mixi-xxx.cc/"
    assert listing_page_url("https://mixi-xxx.cc/", 3) == "https://mixi-xxx.cc/page/3/"
    # page-1 seed that already carries a page number
    assert (
        listing_page_url("https://mixi-xxx.cc/page/1/", 5)
        == "https://mixi-xxx.cc/page/5/"
    )


def test_is_video_page_url() -> None:
    assert is_video_page_url("https://mixi-xxx.cc/scvp-20849/")
    assert is_video_page_url("https://mixi-xxx.cc/some-title/")
    assert not is_video_page_url("https://mixi-xxx.cc/page/2/")
    assert not is_video_page_url("https://mixi-xxx.cc/collection/")
    assert not is_video_page_url("https://other-site.cc/x/")


def test_extract_video_page_links_dedupes() -> None:
    html = """
    <a href="https://mixi-xxx.cc/scvp-20849/">a</a>
    <a href="https://mixi-xxx.cc/scvp-20849/">dup</a>
    <a href="https://mixi-xxx.cc/page/2/">pager</a>
    <a href="https://mixi-xxx.cc/other-video/">b</a>
    """
    links = extract_video_page_links(html, "https://mixi-xxx.cc/")
    assert links == [
        "https://mixi-xxx.cc/scvp-20849/",
        "https://mixi-xxx.cc/other-video/",
    ]


def test_discover_video_pages_with_fetcher() -> None:
    pages = {
        1: '<a href="https://mixi-xxx.cc/video-one/">t1</a>',
        2: '<a href="https://mixi-xxx.cc/video-two/">t2</a>',
    }

    def fetcher(url: str, timeout: float) -> str:
        if url.endswith("/page/2/"):
            return pages[2]
        return pages[1]

    found = discover_video_pages("https://mixi-xxx.cc/", 2, fetcher=fetcher)
    assert dict(found) == {
        "https://mixi-xxx.cc/video-one/": "video-one",
        "https://mixi-xxx.cc/video-two/": "video-two",
    }


def test_extract_embed_url() -> None:
    html = '"embedUrl":"https://luluvdo.com/e/3sj9amxcofja"'
    assert extract_embed_url(html) == "https://luluvdo.com/e/3sj9amxcofja"
    assert extract_embed_url("<html>no embed</html>") is None
