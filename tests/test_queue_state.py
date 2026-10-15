from dler_kun.managers import QueueManager
from dler_kun.models import JobStatus


def test_cancelled_job_cannot_be_completed() -> None:
    queue = QueueManager()
    job = queue.create("download", "test", "url", "out")
    queue.update(job.id, status=JobStatus.RUNNING)
    queue.cancel(job.id)

    completed = queue.finish(job.id, JobStatus.SUCCESS, progress=100, error="")

    assert completed is False
    assert queue.list()[0]["status"] == JobStatus.CANCELLED
    queue.update(job.id, status=JobStatus.RUNNING)
    assert queue.list()[0]["status"] == JobStatus.CANCELLED


def test_completed_job_cannot_be_cancelled_afterward() -> None:
    queue = QueueManager()
    job = queue.create("download", "test", "url", "out")
    queue.update(job.id, status=JobStatus.RUNNING)

    assert queue.finish(job.id, JobStatus.SUCCESS, progress=100, error="") is True
    queue.cancel(job.id)

    assert queue.list()[0]["status"] == JobStatus.SUCCESS
    assert queue.is_cancelled(job.id) is False
