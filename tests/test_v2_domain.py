import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from dler_kun2.domain.contracts import (
    CrawlRequest,
    DownloadRequest,
    EngineCapabilities,
)
from dler_kun2.domain.errors import EngineError, ErrorCode
from dler_kun2.domain.models import CrawlResult, DownloadResult
from dler_kun2.domain.plans import DownloadPlan


def test_engine_error_serializes_common_code_and_retry_delay() -> None:
    error = EngineError(ErrorCode.RATE_LIMITED, "try later", retry_after=12.5)

    assert error.to_dict() == {
        "code": "rate_limited",
        "message": "try later",
        "retry_after": 12.5,
    }
    assert EngineError(ErrorCode.AMBIGUOUS_SERVICE, "unclear").to_dict() == {
        "code": "ambiguous_service",
        "message": "unclear",
        "retry_after": None,
    }


def test_engine_error_rejects_non_finite_retry_delay() -> None:
    for delay in (-1.0, float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError):
            EngineError(ErrorCode.RATE_LIMITED, "try later", retry_after=delay)


def test_plan_repr_and_public_serialization_hide_signed_media_url() -> None:
    secret = "https://cdn.example/movie.mp4?signature=private"
    plan = DownloadPlan(
        media_url=secret,
        source_url="https://example.com/post/1",
        source_page="https://example.com/post/1",
        media_kind="video",
        suggested_name="movie.mp4",
        size=123,
        metadata={"title": "Movie"},
    )

    assert secret not in repr(plan)
    assert "media_url" not in plan.to_dict()
    assert plan.to_dict()["suggested_name"] == "movie.mp4"


def test_requests_and_capabilities_are_immutable() -> None:
    source_options = {"parallel": 2}
    request = DownloadRequest("https://example.com/a", source_options)
    crawl = CrawlRequest("85xo", ("latest",), None, source_options)
    capabilities = EngineCapabilities(download=True, crawl=True)
    source_options["parallel"] = 9

    assert request.options["parallel"] == 2
    assert crawl.options["parallel"] == 2
    with pytest.raises(TypeError):
        request.options["parallel"] = 3
    with pytest.raises(FrozenInstanceError):
        capabilities.download = False


def test_request_rejects_non_json_option_values() -> None:
    for value in (float("nan"), float("inf"), {"nested": "value"}):
        with pytest.raises(ValueError):
            DownloadRequest("https://example.com/a", {"bad": value})


def test_partial_results_keep_counts_paths_and_typed_errors() -> None:
    error = EngineError(ErrorCode.DOWNLOAD_FAILED, "second item failed")
    output = Path("downloads/first.mp4")
    download = DownloadResult(
        output_paths=(output,),
        requested=1,
        discovered=3,
        completed=1,
        unavailable=1,
        errors=(error,),
    )
    crawl = CrawlResult(
        plans=(),
        output_paths=(output,),
        requested=2,
        discovered=3,
        completed=1,
        unavailable=1,
        errors=(error,),
    )

    assert download.completed == crawl.completed == 1
    assert download.unavailable == crawl.unavailable == 1
    assert download.errors == crawl.errors == (error,)
    assert download.output_paths == crawl.output_paths == (output,)


def test_result_rejects_counts_that_claim_more_outputs_than_discovered() -> None:
    with pytest.raises(ValueError):
        DownloadResult(requested=1, discovered=1, completed=1, unavailable=1)
    with pytest.raises(ValueError):
        CrawlResult(requested=1, discovered=1, completed=1, output_paths=())


def test_crawl_result_retains_discovered_plans_without_download() -> None:
    secret = "https://cdn.example/movie.mp4?signature=private"
    plan = DownloadPlan(
        media_url=secret,
        source_url="https://example.com/post/1",
        source_page="https://example.com/post/1",
        media_kind="video",
        suggested_name="movie.mp4",
        size=None,
        metadata={},
    )
    result = CrawlResult(plans=(plan,), requested=1, discovered=1)

    assert result.plans == (plan,)
    assert result.completed == 0
    assert result.output_paths == ()
    assert result.to_dict()["plans"][0]["suggested_name"] == "movie.mp4"
    assert secret not in repr(result)
    assert secret not in json.dumps(result.to_dict(), allow_nan=False)
