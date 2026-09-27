from pathlib import Path

from dler_kun.pathing import unique_path


def test_unique_path_handles_existing_case_insensitive_name(tmp_path: Path) -> None:
    (tmp_path / "sample.JPG").write_bytes(b"one")

    assert unique_path(tmp_path / "sample.jpg") == tmp_path / "sample-2.jpg"
