import asyncio
from pathlib import Path

import pytest

from dler_kun2.domain.plans import DownloadPlan
from dler_kun2.infrastructure.storage.paths import OutputAllocator
from dler_kun2.infrastructure.storage.transfer import TransferService


def plan(name: str, url: str = "https://cdn.example/a") -> DownloadPlan:
    return DownloadPlan(url, url, "https://site.example/", "video", name, None)


@pytest.mark.parametrize("name", ["../outside.mp4", "C:\\outside.mp4", "CON.txt", "a/b.mp4"])
def test_allocator_contains_untrusted_names(tmp_path, name):
    path = OutputAllocator().reserve(plan(name), tmp_path)
    assert path.resolve().parent == tmp_path.resolve()


def test_allocator_disambiguates_casefold_and_url_identity(tmp_path):
    allocator = OutputAllocator()
    first = allocator.reserve(plan("Clip.mp4", "https://cdn.example/one"), tmp_path)
    second = allocator.reserve(plan("clip.MP4", "https://cdn.example/two"), tmp_path)
    same = allocator.reserve(plan("Clip.mp4", "https://cdn.example/one"), tmp_path)
    assert len({first.name.casefold(), second.name.casefold(), same.name.casefold()}) == 3


def test_allocator_reserves_existing_collision(tmp_path):
    (tmp_path / "clip.mp4").write_bytes(b"keep")
    path = OutputAllocator().reserve(plan("clip.mp4"), tmp_path)
    assert path != tmp_path / "clip.mp4"
    assert (tmp_path / "clip.mp4").read_bytes() == b"keep"


def test_transfer_writes_part_then_atomically_completes(tmp_path):
    async def chunks():
        yield b"hello"

    output = tmp_path / "clip.mp4"
    asyncio.run(TransferService().write_chunks(chunks(), output))
    assert output.read_bytes() == b"hello"
    assert not Path(str(output) + ".part").exists()
