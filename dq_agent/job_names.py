"""Persistent display names, separate from datasets and workflow approvals.

Names never become directory names. UUIDs remain the internal job identity, while
a small SQLite registry enforces name uniqueness across application instances.
"""
from __future__ import annotations

import sqlite3
import unicodedata
import uuid
from contextlib import contextmanager
from pathlib import Path
from threading import RLock


MAX_NAME_LENGTH = 80


def name_key(name: str) -> str:
    return unicodedata.normalize("NFKC", name).casefold()


def validate_name(name: str) -> str:
    if not isinstance(name, str):
        raise ValueError("The job name must be text.")
    if any(unicodedata.category(char) in {"Cc", "Cf", "Cs", "Zl", "Zp"} for char in name):
        raise ValueError("Use a single-line job name without control characters.")
    cleaned = unicodedata.normalize("NFC", name.strip())
    if not cleaned:
        raise ValueError("Enter a job name, or leave the new-job field blank for an automatic name.")
    if len(cleaned) > MAX_NAME_LENGTH:
        raise ValueError(f"Keep the job name to {MAX_NAME_LENGTH} characters or fewer.")
    try:
        uuid.UUID(cleaned)
    except ValueError:
        return cleaned
    raise ValueError("Choose a readable job name rather than a UUID identifier.")


class JobNames:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.lock = RLock()
        self.path = self.root / "job_names.sqlite"
        self._check_paths()
        self.connection = sqlite3.connect(str(self.path), timeout=10, check_same_thread=False)
        with self.connection:
            self.connection.execute(
                "CREATE TABLE IF NOT EXISTS job_names ("
                "job_id TEXT PRIMARY KEY, name TEXT NOT NULL, name_key TEXT NOT NULL UNIQUE)"
            )
            self.connection.execute(
                "CREATE TABLE IF NOT EXISTS name_settings (name TEXT PRIMARY KEY, value INTEGER NOT NULL)"
            )
            self.connection.execute(
                "INSERT OR IGNORE INTO name_settings(name, value) VALUES ('next_number', 1)"
            )

    def _check_paths(self):
        for suffix in ("", "-journal", "-wal", "-shm"):
            candidate = self.root / ("job_names.sqlite" + suffix)
            if candidate.is_symlink() or candidate.resolve().parent != self.root:
                raise ValueError("The job-name registry must remain inside the local job store.")

    @contextmanager
    def _write(self):
        with self.lock:
            self._check_paths()
            self.connection.execute("BEGIN IMMEDIATE")
            try:
                yield
                self.connection.commit()
            except BaseException:
                self.connection.rollback()
                raise

    @staticmethod
    def _check_id(job_id: str):
        try:
            if str(uuid.UUID(job_id)) != job_id:
                raise ValueError
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError("Invalid internal job identifier.") from exc

    def _check_available(self, name: str, job_id: str | None = None):
        existing = self.connection.execute("SELECT job_id FROM job_names WHERE name_key = ?", (name_key(name),)).fetchone()
        if existing and existing[0] != job_id:
            raise ValueError("A job already uses that name. Choose a different name.")

    def check_available(self, name: str):
        cleaned = validate_name(name)
        with self.lock:
            self._check_available(cleaned)
        return cleaned

    def _next_name(self) -> str:
        number = self.connection.execute("SELECT value FROM name_settings WHERE name = 'next_number'").fetchone()[0]
        while True:
            name = f"Customer review {number:03d}"
            number += 1
            if not self.connection.execute("SELECT 1 FROM job_names WHERE name_key = ?", (name_key(name),)).fetchone():
                self.connection.execute("UPDATE name_settings SET value = ? WHERE name = 'next_number'", (number,))
                return name

    def assign(self, job_id: str, name: str | None = None) -> str:
        self._check_id(job_id)
        cleaned = validate_name(name) if name is not None else None
        with self._write():
            existing = self.connection.execute("SELECT name FROM job_names WHERE job_id = ?", (job_id,)).fetchone()
            if existing:
                # Another app may have migrated this just-created directory in
                # the brief interval between CSV ingestion and name assignment.
                if cleaned is not None and cleaned != existing[0]:
                    self._check_available(cleaned, job_id)
                    self.connection.execute("UPDATE job_names SET name = ?, name_key = ? WHERE job_id = ?",
                                            (cleaned, name_key(cleaned), job_id))
                    return cleaned
                return existing[0]
            chosen = cleaned if cleaned is not None else self._next_name()
            self._check_available(chosen)
            self.connection.execute("INSERT INTO job_names(job_id, name, name_key) VALUES (?, ?, ?)",
                                    (job_id, chosen, name_key(chosen)))
            return chosen

    def ensure_legacy_names(self, jobs: list[dict]):
        """Oldest unnamed job gets the next number; existing names never change."""
        with self._write():
            for job in sorted(jobs, key=lambda item: (item["created_at"], item["job_id"])):
                job_id = job["job_id"]
                self._check_id(job_id)
                if not self.connection.execute("SELECT 1 FROM job_names WHERE job_id = ?", (job_id,)).fetchone():
                    chosen = self._next_name()
                    self.connection.execute("INSERT INTO job_names(job_id, name, name_key) VALUES (?, ?, ?)",
                                            (job_id, chosen, name_key(chosen)))

    def get(self, job_id: str) -> str | None:
        self._check_id(job_id)
        with self.lock:
            row = self.connection.execute("SELECT name FROM job_names WHERE job_id = ?", (job_id,)).fetchone()
            return row[0] if row else None

    def lookup(self, name: str) -> str | None:
        with self.lock:
            row = self.connection.execute("SELECT job_id FROM job_names WHERE name_key = ?", (name_key(name.strip()),)).fetchone()
            return row[0] if row else None

    def rename(self, job_id: str, name: str) -> str:
        self._check_id(job_id)
        cleaned = validate_name(name)
        with self._write():
            if not self.connection.execute("SELECT 1 FROM job_names WHERE job_id = ?", (job_id,)).fetchone():
                raise ValueError("No saved job matches that name or identifier.")
            self._check_available(cleaned, job_id)
            self.connection.execute("UPDATE job_names SET name = ?, name_key = ? WHERE job_id = ?",
                                    (cleaned, name_key(cleaned), job_id))
        return cleaned

    def remove(self, job_id: str):
        self._check_id(job_id)
        with self._write():
            self.connection.execute("DELETE FROM job_names WHERE job_id = ?", (job_id,))

    def close(self):
        with self.lock:
            self.connection.close()
