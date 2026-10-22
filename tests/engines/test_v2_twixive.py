import asyncio

import pytest

from dler_kun2.domain.contracts import CrawlRequest
from dler_kun2.domain.errors import ErrorCode
from dler_kun2.engines.twixive.adapter import TwixiveEngine


class FakeClient:
    def __init__(self):
        self.trend_calls = []

    async def user_videos(self, identifier, *, limit=50, cursor=None):
        return {"videos": [], "pageInfo": {"hasNextPage": False}}

    async def ranking_videos(self, *, days, limit=50, offset=0):
        return {"items": []}

    async def trend_videos(self, *, limit=50, offset=0):
        self.trend_calls.append((limit, offset))
        return {
            "items": [
                {"video": {"id": str(video_id), "url": f"https://video.twimg.com/{video_id}.mp4"}}
                for video_id in range(1, 4)
            ]
        }


def test_reels_returns_requested_number_of_distinct_videos():
    client = FakeClient()
    engine = TwixiveEngine(client)
    request = CrawlRequest("twixive", ("https://twixive.net/reels",), None, {"limit": 2})

    result = asyncio.run(engine.crawl(request))

    assert len(result.plans) == 2
    assert len({plan.suggested_name for plan in result.plans}) == 2
    assert result.discovered == 2
    assert result.requested == 1
    assert client.trend_calls == [(50, 0)]


@pytest.mark.parametrize(
    "url",
    [
        "https://twixive.net.evil.example/user/alice",
        "https://alice@twixive.net/user/alice",
        "https://twixive.net/ranking/30days",
    ],
)
def test_invalid_twiXive_routes_are_rejected(url):
    engine = TwixiveEngine(FakeClient())
    request = CrawlRequest("twixive", (url,), None, {})

    result = asyncio.run(engine.crawl(request))

    assert result.errors
    assert result.errors[0].code is ErrorCode.INVALID_REQUEST
