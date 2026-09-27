import os

from dler_kun.engines.gofile.gofile_dl.downloader.go_file_downloader import (
    _reserve_unique_file_names,
)


def test_reserve_unique_file_names_handles_windows_case_collisions() -> None:
    files = [
        {"name": os.path.join("リスト", "83.JPG"), "link": "https://cdn/one"},
        {"name": os.path.join("リスト", "83.jpg"), "link": "https://cdn/two"},
    ]

    result = _reserve_unique_file_names(files)

    assert [item["name"] for item in result] == [
        os.path.join("リスト", "83.JPG"),
        os.path.join("リスト", "83-2.jpg"),
    ]
