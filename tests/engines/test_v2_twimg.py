import asyncio
from pathlib import Path

from dler_kun2.domain.contracts import DownloadRequest
from dler_kun2.domain.errors import ErrorCode
from dler_kun2.engines.twimg.adapter import TwimgEngine


def test_unverified_twimg_hosts_remain_quarantined() -> None:
    from dler_kun2.routing.registry import EngineRegistry, RouteError

    try:
        EngineRegistry().resolve("https://twimg.jp/item")
    except RouteError as exc:
        assert exc.error.code is ErrorCode.AMBIGUOUS_SERVICE
    else:
        raise AssertionError("unverified Twimg ownership must not resolve")


def test_vendor_invocation_discovers_only_new_media_files(tmp_path: Path, monkeypatch) -> None:
    script = tmp_path / "download_twitter_media.py"
    script.write_text("# test tool", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    output = Path("out")
    media = Path("nested") / "clip.mp4"

    class Process:
        returncode: int | None = 0

        async def communicate(self) -> tuple[bytes | None, bytes | None]:
            staged_media = staging / media
            staged_media.parent.mkdir(parents=True)
            staged_media.write_bytes(b"media")
            (staging / "twimg.db").write_bytes(b"temporary history")
            return b"done", b""

        def terminate(self) -> None:
            raise AssertionError("successful process should not be terminated")

        async def wait(self) -> int:
            return self.returncode or 0

    async def runner(*command, **_kwargs):
        nonlocal staging
        staging = Path(command[command.index("-o") + 1])
        return Process()

    staging = Path()
    engine = TwimgEngine(script_path=script, process_runner=runner)
    paths = asyncio.run(
        engine.run_vendor(DownloadRequest("https://example.invalid/x", {}), output)
    )

    assert len(paths) == 1
    assert paths[0].parent == (tmp_path / output)
    assert paths[0].suffix == ".mp4"
    assert paths[0].read_bytes() == b"media"
    assert not tuple((tmp_path / output).rglob("twimg.db"))


def test_vendor_options_preserve_legacy_worker_quality_and_interface_flags(tmp_path: Path) -> None:
    script = tmp_path / "tool.py"
    script.write_text("# tool", encoding="utf-8")
    commands = []

    class Process:
        returncode: int | None = 0

        async def communicate(self) -> tuple[bytes | None, bytes | None]:
            return b"", b""

        def terminate(self) -> None:
            raise AssertionError("successful process should not be terminated")

        async def wait(self) -> int:
            return 0

    async def runner(*command, **_kwargs):
        commands.append(command)
        staging = Path(command[command.index("-o") + 1])
        (staging / "clip.mp4").write_bytes(b"media")
        return Process()

    request = DownloadRequest("https://example.invalid/clip", {
        "force": True, "verbose": True, "parallel": 7, "seg_workers": 5,
        "quality": "1080p", "local_addr": "192.0.2.4",
    })
    asyncio.run(TwimgEngine(script_path=script, process_runner=runner).run_vendor(request, tmp_path / "out"))
    command = commands[0]
    for flag_value in (("--force",), ("--verbose",), ("-p", "7"), ("-w", "5"), ("-q", "1080p"), ("--local-addr", "192.0.2.4")):
        assert all(part in command for part in flag_value)


def test_missing_vendor_reports_dependency_missing(tmp_path: Path) -> None:
    engine = TwimgEngine(script_path=tmp_path / "absent.py")
    try:
        asyncio.run(
            engine.run_vendor(DownloadRequest("https://example.invalid/x", {}), tmp_path / "out")
        )
    except Exception as exc:
        assert getattr(exc, "code", None) is ErrorCode.DEPENDENCY_MISSING
    else:
        raise AssertionError("missing vendor must be reported")


def test_vendor_outputs_with_identical_names_never_overwrite(tmp_path: Path) -> None:
    script = tmp_path / "tool.py"
    script.write_text("# test", encoding="utf-8")

    class Process:
        returncode: int | None = 0

        async def communicate(self) -> tuple[bytes | None, bytes | None]:
            for folder, name, content in (("a", "CLIP.mp4", b"first"), ("b", "clip.mp4", b"second")):
                target = staging / folder / name
                target.parent.mkdir(parents=True)
                target.write_bytes(content)
            return b"", b""

        def terminate(self) -> None:
            pass

        async def wait(self) -> int:
            return 0

    async def runner(*command, **_kwargs):
        nonlocal staging
        staging = Path(command[command.index("-o") + 1])
        return Process()

    staging = tmp_path
    output = tmp_path / "out"
    engine = TwimgEngine(script_path=script, process_runner=runner)
    request = DownloadRequest("https://example.invalid/clip")
    first = asyncio.run(engine.run_vendor(request, output))
    second = asyncio.run(engine.run_vendor(request, output))
    assert len(first + second) == 4
    assert len({path.name.casefold() for path in first + second}) == 4
    assert sorted(path.read_bytes() for path in first + second) == [b"first", b"first", b"second", b"second"]


def test_resolution_plan_redacts_signed_source_query() -> None:
    plan = asyncio.run(
        TwimgEngine().resolve_download(
            DownloadRequest("https://example.invalid/private/path?token=secret")
        )
    )
    assert "secret" not in repr(plan)
    assert "secret" not in str(plan.to_dict())
    assert "private/path" not in str(plan.to_dict())


def test_missing_python_runtime_is_normalized(tmp_path: Path) -> None:
    script = tmp_path / "tool.py"
    script.write_text("# tool", encoding="utf-8")

    async def missing(*_args, **_kwargs):
        raise FileNotFoundError("python")

    engine = TwimgEngine(script_path=script, process_runner=missing)
    try:
        asyncio.run(
            engine.run_vendor(DownloadRequest("https://example.invalid/x", {}), tmp_path / "out")
        )
    except Exception as exc:
        assert getattr(exc, "code", None) is ErrorCode.DEPENDENCY_MISSING
    else:
        raise AssertionError("missing runtime must be reported")


def test_cancellation_terminates_managed_vendor_process(tmp_path: Path) -> None:
    script = tmp_path / "download_twitter_media.py"
    script.write_text("# test tool", encoding="utf-8")
    terminated = asyncio.Event()

    class Process:
        returncode: int | None = None

        async def communicate(self) -> tuple[bytes | None, bytes | None]:
            await asyncio.Event().wait()
            return b"", b""

        def terminate(self) -> None:
            terminated.set()

        async def wait(self) -> int:
            self.returncode = -15
            return self.returncode

    async def runner(*_args, **_kwargs):
        return Process()

    async def scenario():
        engine = TwimgEngine(script_path=script, process_runner=runner)
        cancel = asyncio.Event()
        task = asyncio.create_task(
            engine.run_vendor(
                DownloadRequest("https://example.invalid/x", {}),
                tmp_path / "out",
                cancel=cancel,
            )
        )
        await asyncio.sleep(0)
        cancel.set()
        try:
            await task
        except asyncio.CancelledError:
            pass
        assert terminated.is_set()

    asyncio.run(scenario())
