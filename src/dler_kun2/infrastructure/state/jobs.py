"""SQLite-backed jobs with atomic cross-process cancellation."""

import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

_TERMINAL = {"succeeded", "failed", "cancelled"}


@dataclass(frozen=True)
class Job:
    id: str
    kind: str
    status: str
    cancel_requested: bool


class JobStore:
    def __init__(self, database: str | Path):
        self.database = str(database)
        Path(self.database).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, kind TEXT NOT NULL, "
                "status TEXT NOT NULL, cancel_requested INTEGER NOT NULL DEFAULT 0)"
            )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database, timeout=10)
        try:
            connection.execute("PRAGMA journal_mode=WAL")
            with connection:
                yield connection
        finally:
            connection.close()

    def create(self, kind: str) -> str:
        job_id = uuid.uuid4().hex
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO jobs (id, kind, status) VALUES (?, ?, 'queued')",
                (job_id, kind),
            )
        return job_id

    def get(self, job_id: str) -> Job:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT id, kind, status, cancel_requested FROM jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
        if row is None:
            raise KeyError(job_id)
        return Job(row[0], row[1], row[2], bool(row[3]))

    def transition(self, job_id: str, status: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE jobs SET status = ? WHERE id = ? AND status NOT IN (?, ?, ?)",
                (status, job_id, *_TERMINAL),
            )
            return cursor.rowcount == 1

    def cancel(self, job_id: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE jobs SET cancel_requested = 1 WHERE id = ? AND status NOT IN (?, ?, ?)",
                (job_id, *_TERMINAL),
            )
            return cursor.rowcount == 1

    def is_cancelled(self, job_id: str) -> bool:
        return self.get(job_id).cancel_requested
