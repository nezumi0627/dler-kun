import multiprocessing

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
