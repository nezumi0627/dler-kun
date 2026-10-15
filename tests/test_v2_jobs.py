import multiprocessing
import sqlite3

from dler_kun2.infrastructure.state.jobs import JobStore


def _cancel_from_process(database: str, job_id: str):
    JobStore(database).cancel(job_id)


def test_cancel_from_second_process_and_terminal_state_immutable(tmp_path):
    database = str(tmp_path / "jobs.sqlite3")
    store = JobStore(database)
    job = store.create("download")
    process = multiprocessing.Process(target=_cancel_from_process, args=(database, job))
    process.start()
    process.join(5)
    assert process.exitcode == 0
    assert store.is_cancelled(job)
    store.transition(job, "cancelled")
    assert store.transition(job, "succeeded") is False
    assert store.get(job).status == "cancelled"


def test_each_sqlite_operation_closes_its_connection(tmp_path, monkeypatch):
    import dler_kun2.infrastructure.state.jobs as jobs_module

    opened = []
    real_connect = sqlite3.connect

    class TrackedConnection:
        def __init__(self, *args, **kwargs):
            self.connection = real_connect(*args, **kwargs)
            self.closed = False
            opened.append(self)

        def __getattr__(self, name):
            return getattr(self.connection, name)

        def __enter__(self):
            self.connection.__enter__()
            return self

        def __exit__(self, *args):
            return self.connection.__exit__(*args)

        def close(self):
            self.closed = True
            self.connection.close()

    monkeypatch.setattr(jobs_module.sqlite3, "connect", TrackedConnection)
    store = JobStore(tmp_path / "jobs.sqlite3")
    job_id = store.create("download")
    store.get(job_id)
    store.cancel(job_id)
    assert opened
    assert all(connection.closed for connection in opened)
