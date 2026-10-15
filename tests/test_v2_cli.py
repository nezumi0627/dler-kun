import asyncio
import json
import threading
import time
from pathlib import Path

import pytest

from dler_kun2.application.crawl import crawl
from dler_kun2.application.download import download, download_many
from dler_kun2.domain.contracts import EngineCapabilities
from dler_kun2.domain.errors import EngineError, ErrorCode
from dler_kun2.domain.models import CrawlResult
from dler_kun2.domain.plans import DownloadPlan
from dler_kun2.infrastructure.state.jobs import JobStore
from dler_kun2.presentation.cli.commands import run_command
from dler_kun2.presentation.cli.main import main
from dler_kun2.presentation.cli.output import emit
from dler_kun2.routing.registry import EngineRegistry, RouteError
from dler_kun2.routing.rules import RouteRule

SECRET = "https://cdn.example/media.mp4?signature=secret"


class Engine:
    engine_id = "sample"
    capabilities = EngineCapabilities(download=True, crawl=True)

    def __init__(self):
        self.last_crawl_request = None

    async def resolve_download(self, request):
        assert not hasattr(request, "output_dir")
        return DownloadPlan(SECRET, request.url, request.url, "video", "file.mp4", None)

    async def crawl(self, request):
        self.last_crawl_request = request
        assert not hasattr(request, "download")
        if not request.seeds:
            return CrawlResult(requested=0, discovered=0)
        return CrawlResult(plans=(await self.resolve_download(type("R", (), {"url": request.seeds[0]})()),), requested=1, discovered=1)

    async def ranking(self, request):
        raise NotImplementedError


class Transfer:
    async def transfer(self, plan, output_dir):
        return output_dir / plan.suggested_name


def registry(engine: Engine | None = None):
    result = EngineRegistry()
    result.register(engine or Engine(), [RouteRule("sample", ("sample.test",))])
    return result


def test_download_resolves_plan_and_transfers_at_application_boundary(tmp_path):
    result = asyncio.run(download("https://sample.test/1", tmp_path, registry(), Transfer()))
    assert result.completed == 1
    assert result.output_paths == (tmp_path / "file.mp4",)


def test_download_many_keeps_successes_when_one_url_fails(tmp_path):
    class MixedEngine(Engine):
        async def resolve_download(self, request):
            if request.url.endswith("bad"):
                raise EngineError(ErrorCode.NOT_FOUND, "missing")
            return DownloadPlan(SECRET, request.url, request.url, "video", request.url.rsplit("/", 1)[-1] + ".mp4", None)

    class NamedTransfer:
        async def transfer(self, plan, output_dir):
            return output_dir / plan.suggested_name

    result = asyncio.run(
        download_many(
            ("https://sample.test/one", "https://sample.test/bad", "https://sample.test/two"),
            tmp_path,
            registry(MixedEngine()),
            NamedTransfer(),
        )
    )
    assert result.requested == 3
    assert result.discovered == 2
    assert result.completed == 2
    assert {path.name for path in result.output_paths} == {"one.mp4", "two.mp4"}
    assert [error.code for error in result.errors] == [ErrorCode.NOT_FOUND]


def test_crawl_retains_plans_and_only_transfers_on_request(tmp_path):
    found = asyncio.run(crawl("sample", ("https://sample.test/1",), None, tmp_path, registry(), Transfer()))
    saved = asyncio.run(crawl("sample", ("https://sample.test/1",), None, tmp_path, registry(), Transfer(), download_items=True))
    assert found.completed == 0 and len(found.plans) == 1
    assert saved.completed == 1 and saved.plans == found.plans


def test_crawl_uses_engine_plan_downloader_for_browser_bound_media(tmp_path):
    class BrowserEngine(Engine):
        async def crawl(self, request):
            return CrawlResult(plans=(DownloadPlan("https://player.example/embed", "https://mixi.test/", "https://mixi.test/1", "browser_hls", "clip.mp4", None),), requested=1, discovered=1)

        async def download_plan(self, plan, output_dir):
            assert plan.media_kind == "browser_hls"
            return output_dir / plan.suggested_name

    result = asyncio.run(crawl("sample", (), None, tmp_path, registry(BrowserEngine()), Transfer(), download_items=True))
    assert result.completed == 1
    assert result.output_paths == (tmp_path / "clip.mp4",)


def test_unsupported_capability_is_typed(tmp_path):
    with pytest.raises(RouteError) as exc:
        from dler_kun2.application.ranking import ranking
        asyncio.run(ranking("sample", ("https://sample.test/1",), None, tmp_path, registry()))
    assert exc.value.error.code is ErrorCode.UNSUPPORTED_CAPABILITY


def test_cli_sites_json_reports_verified_engines(capsys):
    assert main(["sites", "--json"]) == 0
    ids = {item["engine_id"] for item in json.loads(capsys.readouterr().out)["sites"]}
    assert ids == {"85xo", "gofile", "gofilerun", "linkex", "mixixxx", "mvfile", "videy"}


def test_cli_download_accepts_multiple_urls(capsys, monkeypatch):
    captured = {}

    def run(command, target, _registry, **kwargs):
        captured.update(command=command, target=target, targets=kwargs["targets"], parallel_urls=kwargs["parallel_urls"])
        return {"accepted": list(kwargs["targets"])}

    monkeypatch.setattr("dler_kun2.presentation.cli.main.run_command", run)
    assert main(["download", "https://sample.test/a", "https://sample.test/b", "--parallel-urls", "2", "--json"]) == 0
    assert captured["command"] == "download"
    assert captured["target"] == "https://sample.test/a"
    assert captured["targets"] == ("https://sample.test/a", "https://sample.test/b")
    assert captured["parallel_urls"] == 2
    assert json.loads(capsys.readouterr().out)["accepted"] == list(captured["targets"])


@pytest.mark.parametrize("command", ["detect", "download", "crawl", "ranking", "jobs", "cancel", "config"])
def test_cli_json_is_valid_for_every_command(command, capsys):
    args = [command]
    if command in {"detect", "download"}:
        args.append("https://unknown.test/item")
    if command in {"crawl", "ranking"}:
        args.append("unknown-engine" if command == "crawl" else "gofile")
    if command == "cancel":
        args.append("job-1")
    args.append("--json")
    assert main(args) in (0, 2)
    assert isinstance(json.loads(capsys.readouterr().out), dict)


def test_cli_does_not_claim_pending_download_works(capsys):
    assert main(["download", "https://gofilelab.com/item", "--json"]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == "ambiguous_service"


@pytest.mark.parametrize(("command", "service"), [("crawl", "unknown-engine"), ("ranking", "gofile")])
def test_crawl_and_ranking_accept_service_without_seed(command, service, capsys):
    assert main([command, service, "--json"]) == 2
    expected = "invalid_request" if command == "ranking" else "unsupported_service"
    assert json.loads(capsys.readouterr().out)["error"]["code"] == expected


def test_crawl_passes_optional_seed_and_days_to_application(tmp_path):
    engine = Engine()
    installed = registry(engine)
    result = run_command("crawl", "sample", installed, output_dir=tmp_path, seeds=("https://sample.test/1",), days=3)
    assert isinstance(result, CrawlResult)
    assert len(result.plans) == 1
    assert engine.last_crawl_request is not None
    assert engine.last_crawl_request.days == 3


def test_cli_crawl_accepts_v1_seed_and_days_flags(capsys, monkeypatch):
    engine = Engine()
    installed = registry(engine)
    monkeypatch.setattr("dler_kun2.presentation.cli.main.EngineRegistry", lambda: installed)
    assert main(["crawl", "sample", "--seed", "https://sample.test/1", "--days", "3", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["plans"][0]["source_url"] == "https://sample.test/1"
    assert engine.last_crawl_request is not None
    assert engine.last_crawl_request.days == 3


def test_text_output_is_concise_and_redacted(capsys):
    result = asyncio.run(crawl("sample", ("https://sample.test/1",), None, Path("downloads"), registry()))
    emit(result, json_mode=False)
    output = capsys.readouterr().out
    assert "discovered 1" in output
    assert "plans" not in output
    assert "metadata" not in output
    assert SECRET not in output


def test_cli_jobs_and_cancel_use_persistent_state_store(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DLER_KUN2_DATA_DIR", str(tmp_path))
    store = JobStore(tmp_path / "jobs.sqlite3")
    job_id = store.create("download")

    assert main(["jobs", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["jobs"][0]["id"] == job_id
    assert main(["cancel", job_id, "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["cancel_requested"] is True
    assert main(["cancel", "--all", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["cancelled"] == 0


def test_cli_cancel_interrupts_running_crawl_and_records_terminal_state(tmp_path, monkeypatch):
    monkeypatch.setenv("DLER_KUN2_DATA_DIR", str(tmp_path))

    class SlowEngine(Engine):
        async def crawl(self, request):
            await asyncio.sleep(30)
            return CrawlResult()

    store = JobStore(tmp_path / "jobs.sqlite3")
    outcome = []
    worker = threading.Thread(
        target=lambda: outcome.append(
            run_command("crawl", "sample", registry(SlowEngine()), output_dir=tmp_path)
        ),
        daemon=True,
    )
    worker.start()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        jobs = store.list()
        if jobs and jobs[0].status == "running":
            break
        time.sleep(0.02)
    else:
        raise AssertionError("crawl did not create a running job")

    assert store.cancel(jobs[0].id)
    worker.join(5)

    assert not worker.is_alive()
    assert len(outcome) == 1
    assert getattr(outcome[0], "code", None) is ErrorCode.CANCELLED
    job = store.get(jobs[0].id)
    assert job.status == "cancelled"
