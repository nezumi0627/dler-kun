import asyncio
import json

import pytest

from dler_kun2.application.crawl import crawl
from dler_kun2.application.download import download
from dler_kun2.domain.contracts import EngineCapabilities
from dler_kun2.domain.errors import ErrorCode
from dler_kun2.domain.models import CrawlResult
from dler_kun2.domain.plans import DownloadPlan
from dler_kun2.presentation.cli.main import main
from dler_kun2.routing.registry import EngineRegistry, RouteError
from dler_kun2.routing.rules import RouteRule

SECRET = "https://cdn.example/media.mp4?signature=secret"


class Engine:
    engine_id = "sample"
    capabilities = EngineCapabilities(download=True, crawl=True)

    async def resolve_download(self, request):
        assert not hasattr(request, "output_dir")
        return DownloadPlan(SECRET, request.url, request.url, "video", "file.mp4", None)

    async def crawl(self, request):
        assert not hasattr(request, "download")
        return CrawlResult(plans=(await self.resolve_download(type("R", (), {"url": request.seeds[0]})()),), requested=1, discovered=1)

    async def ranking(self, request):
        raise NotImplementedError


class Transfer:
    async def transfer(self, plan, output_dir):
        return output_dir / plan.suggested_name


def registry():
    result = EngineRegistry()
    result.register(Engine(), [RouteRule("sample", ("sample.test",))])
    return result


def test_download_resolves_plan_and_transfers_at_application_boundary(tmp_path):
    result = asyncio.run(download("https://sample.test/1", tmp_path, registry(), Transfer()))
    assert result.completed == 1
    assert result.output_paths == (tmp_path / "file.mp4",)


def test_crawl_retains_plans_and_only_transfers_on_request(tmp_path):
    found = asyncio.run(crawl("sample", ("https://sample.test/1",), None, tmp_path, registry(), Transfer()))
    saved = asyncio.run(crawl("sample", ("https://sample.test/1",), None, tmp_path, registry(), Transfer(), download_items=True))
    assert found.completed == 0 and len(found.plans) == 1
    assert saved.completed == 1 and saved.plans == found.plans


def test_unsupported_capability_is_typed(tmp_path):
    with pytest.raises(RouteError) as exc:
        from dler_kun2.application.ranking import ranking
        asyncio.run(ranking("sample", ("https://sample.test/1",), None, tmp_path, registry()))
    assert exc.value.error.code is ErrorCode.UNSUPPORTED_CAPABILITY


def test_cli_sites_json_reports_no_registered_engines(capsys):
    assert main(["sites", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == {"sites": []}


@pytest.mark.parametrize("command", ["detect", "download", "crawl", "ranking", "jobs", "cancel", "config"])
def test_cli_json_is_valid_for_every_command(command, capsys):
    args = [command]
    if command in {"detect", "download", "crawl", "ranking"}:
        args.append("https://unknown.test/item")
    if command == "cancel":
        args.append("job-1")
    args.append("--json")
    assert main(args) in (0, 2)
    assert isinstance(json.loads(capsys.readouterr().out), dict)


def test_cli_does_not_claim_pending_download_works(capsys):
    assert main(["download", "https://gofile.io/d/1", "--json"]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == "unsupported_service"
