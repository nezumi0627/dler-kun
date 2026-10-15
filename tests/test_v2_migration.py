from dler_kun2.infrastructure.state.migration import StateMigrator


def test_migration_is_idempotent_and_preserves_source(tmp_path):
    old = tmp_path / "old"
    new = tmp_path / "new"
    (old / "cache").mkdir(parents=True)
    (old / "config.json").write_bytes(b'{"output":"downloads"}')
    (old / "cache" / "entry.bin").write_bytes(b"cached")
    (old / "downloads").mkdir()
    (old / "downloads" / "media.mp4").write_bytes(b"large media")
    migrator = StateMigrator()
    assert migrator.migrate(old, new) == 2
    assert migrator.migrate(old, new) == 2
    assert (new / "config.json").read_bytes() == b'{"output":"downloads"}'
    assert (new / "cache" / "entry.bin").read_bytes() == b"cached"
    assert (old / "config.json").read_bytes() == b'{"output":"downloads"}'
    assert (old / "cache" / "entry.bin").read_bytes() == b"cached"
    assert not (new / "downloads").exists()


def test_migration_rejects_symlink_destination_parent(tmp_path):
    old = tmp_path / "old"
    new = tmp_path / "new"
    outside = tmp_path / "outside"
    (old / "cache").mkdir(parents=True)
    (old / "cache" / "entry.bin").write_bytes(b"state")
    outside.mkdir()
    new.mkdir()
    (new / "cache").symlink_to(outside, target_is_directory=True)
    try:
        StateMigrator().migrate(old, new)
    except ValueError:
        pass
    else:
        raise AssertionError("migration accepted a symlink destination")
    assert list(outside.iterdir()) == []


def test_migration_rejects_dangling_symlink_destination(tmp_path):
    old = tmp_path / "old"
    new = tmp_path / "new"
    (old / "cache").mkdir(parents=True)
    (old / "cache" / "entry.bin").write_bytes(b"state")
    new.mkdir()
    (new / "cache").symlink_to(tmp_path / "missing", target_is_directory=True)
    try:
        StateMigrator().migrate(old, new)
    except ValueError:
        pass
    else:
        raise AssertionError("migration accepted a dangling symlink destination")
