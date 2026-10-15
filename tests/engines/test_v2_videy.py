from pathlib import Path

import pytest

from dler_kun2.domain.contracts import DownloadRequest
from dler_kun2.domain.errors import EngineError, ErrorCode
from dler_kun2.engines.videy.adapter import VideyEngine
from dler_kun2.engines.videy.parser import parse_player
from dler_kun2.routing.defaults import build_registry

FIXTURES = Path(__file__).parents[1] / "fixtures" / "videy"


def test_current_player_contract_resolves_id_and_media_extension() -> None:
    page = (FIXTURES / "player-contract.html").read_text(encoding="utf-8")
    bundle_excerpt = (FIXTURES / "player-contract.js").read_text(encoding="utf-8")

    media = parse_player("https://videy.co/v?id=AbCd1234", page, bundle_excerpt)

    assert media == ("AbCd1234", "https://cdn.videy.co/AbCd1234.mp4", "mp4")


def test_videy_id_is_validated_before_building_cdn_url() -> None:
    with pytest.raises(ValueError, match="video id"):
        parse_player("https://videy.co/v?id=bad%2Fid", "", "")


def test_player_requires_id_in_current_query_parameter() -> None:
    with pytest.raises(ValueError, match="video id"):
        parse_player("https://videy.co/v", "", "")


def test_verified_twimg_path_resolves_only_matching_videy_cdn_source() -> None:
    page = '<video><source src="https://cdn.videy.co/lZwuUiqZ1.mp4" type="video/mp4"></video>'
    assert parse_player("https://video.twimg.it.com/lZwuUiqZ1.mp4", page, "") == (
        "lZwuUiqZ1", "https://cdn.videy.co/lZwuUiqZ1.mp4", "mp4"
    )
    with pytest.raises(ValueError, match="matching CDN"):
        parse_player("https://video.twimg.it.com/lZwuUiqZ1.mp4", '<source src="https://evil.example/video.mp4">', "")


def test_only_verified_videy_backends_are_registered() -> None:
    assert build_registry().resolve("https://videy.co/v?id=AbCd1234").engine_id == "videy"
    assert build_registry().resolve("https://video.twimg.it.com/lZwuUiqZ1.mp4").engine_id == "videy"


def test_adapter_plan_keeps_media_url_out_of_public_representation() -> None:
    class Response:
        async def text(self):
            return "<div id='root'></div>"

    class Http:
        async def request(self, *_args, **_kwargs):
            return Response()

    import asyncio

    plan = asyncio.run(
        VideyEngine(Http()).resolve_download(
            DownloadRequest("https://videy.co/v?id=AbCd1234&signature=secret")
        )
    )

    assert plan.media_url.endswith("AbCd1234.mp4")
    assert "cdn.videy.co" not in repr(plan)
    assert "media_url" not in plan.to_dict()
    assert "signature" not in str(plan.to_dict())


def test_mirror_plan_uses_verified_cdn_and_sanitized_source_url() -> None:
    class Response:
        async def text(self):
            return '<video><source src="https://cdn.videy.co/lZwuUiqZ1.mp4"></video>'

    class Http:
        async def request(self, *_args, **_kwargs):
            return Response()

    import asyncio

    plan = asyncio.run(VideyEngine(Http()).resolve_download(
        DownloadRequest("https://video.twimg.it.com/lZwuUiqZ1.mp4?token=private")
    ))
    assert plan.media_url == "https://cdn.videy.co/lZwuUiqZ1.mp4"
    assert plan.source_url == "https://video.twimg.it.com/lZwuUiqZ1.mp4"
    assert "private" not in str(plan.to_dict())


def test_adapter_maps_invalid_urls_and_http_rate_limit():
    import asyncio

    from dler_kun2.infrastructure.http.client import HttpError

    class Response:
        async def text(self):
            return ""

    class InvalidHttp:
        async def request(self, *_args, **_kwargs):
            return Response()

    with pytest.raises(EngineError) as invalid:
        asyncio.run(VideyEngine(InvalidHttp()).resolve_download(DownloadRequest("https://videy.co/v")))
    assert invalid.value.code is ErrorCode.INVALID_REQUEST

    class LimitedHttp:
        async def request(self, *_args, **_kwargs):
            raise HttpError(ErrorCode.RATE_LIMITED, "private", 12)

    with pytest.raises(EngineError) as limited:
        asyncio.run(VideyEngine(LimitedHttp()).resolve_download(DownloadRequest("https://videy.co/v?id=AbCd1234")))
    assert limited.value.code is ErrorCode.RATE_LIMITED
    assert limited.value.retry_after == 12
