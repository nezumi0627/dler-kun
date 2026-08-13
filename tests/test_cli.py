from dler_kun.cli import (
    _exit_code_from_status,
    _status_tag,
    print_detect,
    print_job_result,
    print_sites,
)


def test_status_tag() -> None:
    assert _status_tag("success") == "[SUCCESS]"
    assert _status_tag("failed") == "[ERROR]"
    assert _status_tag("cancelled") == "[WARNING]"
    assert _status_tag("unsupported") == "[ERROR]"


def test_exit_code_from_status() -> None:
    assert _exit_code_from_status("success") == 0
    assert _exit_code_from_status("cancelled") == 0
    assert _exit_code_from_status("failed") == 1
    assert _exit_code_from_status("unknown") == 1


def test_print_detect(capsys) -> None:
    assert print_detect({"supported": True, "engine_id": "85xo"}) == 0
    assert "[SUCCESS] 85xo" in capsys.readouterr().out
    assert print_detect({"supported": False, "message": "unsupported"}) == 1


def test_print_sites_json(capsys) -> None:
    sites = {"85xo": ["85xo.com"], "mixixxx": ["mixi-xxx.cc"]}
    assert print_sites(sites, as_json=True) == 0
    out = capsys.readouterr().out
    assert '"85xo"' in out
    assert '"mixixxx"' in out


def test_print_job_result_success(capsys) -> None:
    result = {
        "status": "success",
        "engine_id": "mixixxx",
        "message": "mixixxx crawl completed: 2 item(s).",
        "items": [1, 2],
        "files": ["a.mp4"],
    }
    assert print_job_result(result) == 0
    out = capsys.readouterr().out
    assert "[SUCCESS]" in out
    assert "items: 2" in out
    assert "files: 1" in out
