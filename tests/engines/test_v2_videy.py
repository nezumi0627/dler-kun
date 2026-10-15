from pathlib import Path

import pytest

from dler_kun2.domain.contracts import DownloadRequest
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


def test_only_verified_videy_host_is_registered() -> None:
    assert build_registry().resolve("https://videy.co/v?id=AbCd1234").engine_id == "videy"


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
