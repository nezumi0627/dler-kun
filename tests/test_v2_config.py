import json

import pytest

from dler_kun2.domain.errors import EngineError, ErrorCode
from dler_kun2.infrastructure.state.config import ConfigStore
from dler_kun2.presentation.cli.main import main


def test_config_merges_defaults_and_redacts_secrets(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"threads": 8, "gofile": {"api_key": "secret"}, "proxy": "http://user:pass@proxy.test:8080"}), encoding="utf-8")

    store = ConfigStore(path)
    config = store.as_dict()
    assert config["threads"] == 8
    assert config["timeout"] == 30
    assert config["gofile"]["api_key"] == "[REDACTED]"
    assert config["proxy"] == "[REDACTED]"
    assert store.as_dict(redact=False)["gofile"]["api_key"] == "secret"


def test_config_rejects_non_object_and_invalid_json(tmp_path):
    path = tmp_path / "config.json"
    for contents in ("not json", "[]"):
        path.write_text(contents, encoding="utf-8")
        with pytest.raises(EngineError) as failure:
            ConfigStore(path)
        assert failure.value.code is ErrorCode.INVALID_REQUEST


def test_config_save_is_atomic_and_private_on_posix(tmp_path):
    path = tmp_path / "nested" / "config.json"
    store = ConfigStore(path)
    store.save()
    assert json.loads(path.read_text(encoding="utf-8"))["output_dir"] == "downloads"
    assert not list(path.parent.glob("*.tmp"))
    if __import__("os").name != "nt":
        assert path.stat().st_mode & 0o777 == 0o600


def test_config_cli_saves_defaults_without_printing_secrets(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["config", "--save", "--json"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["saved"] is True
    assert (tmp_path / "config.json").is_file()
    assert "cookie" not in output["config"] or output["config"]["cookie"] == ""
