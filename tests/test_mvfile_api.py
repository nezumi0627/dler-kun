from dler_kun.engines.mvfile import api


def _nested_entry(short_link: str, name: str) -> dict[str, object]:
    return {
        "netDiskInfo": {
            "shortLink": short_link,
            "name": name,
            "isFolder": False,
            "fileUrl": f"https://cdn.example/{short_link}.mp4",
        }
    }


def test_list_entries_parses_gofile_bar_nested_items(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    def fake_api_get(endpoint, params, *, referer, timeout_seconds):
        calls.append(params)
        return {
            "data": {
                "list": [
                    _nested_entry("c3dQVq", "first"),
                    _nested_entry("bPFBH3", "second"),
                ],
                "total": 2,
            }
        }

    monkeypatch.setattr(api, "_api_get", fake_api_get)
    entries = api.list_entries("cs5AeP", domain="gofile.bar")

    assert [entry.short_link for entry in entries] == ["c3dQVq", "bPFBH3"]
    assert all(entry.media_url for entry in entries)
    assert calls[0]["domain"] == "gofile.bar"


def test_related_non_folder_root_expands_same_channel(monkeypatch) -> None:
    root = api.MvfileEntry(
        short_link="cs5AeP",
        name="root",
        is_folder=False,
        page_url="https://gofile.bar/d/cs5AeP",
        channel_link="cs5AeP",
    )
    listed = api.MvfileEntry(
        short_link="c3dQVq",
        name="child",
        is_folder=False,
        page_url="https://gofile.bar/d/c3dQVq",
        media_url="https://cdn.example/c3dQVq.mp4",
    )
    monkeypatch.setattr(api, "fetch_info", lambda *args, **kwargs: root)
    monkeypatch.setattr(api, "list_entries", lambda *args, **kwargs: [listed])

    targets = api.resolve_download_targets(
        "https://gofile.bar/d/cs5AeP", related=True
    )

    assert [target.short_link for target in targets] == ["c3dQVq"]
