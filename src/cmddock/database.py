from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterable
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cmddock.models import CommandStatus


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class Database:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.initialize()

    @contextmanager
    def connect(self) -> Iterable[sqlite3.Connection]:
        conn = sqlite3.connect(self.database_path, detect_types=sqlite3.PARSE_DECLTYPES)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def initialize(self) -> None:
        with self._lock, self.connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS commands (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    command TEXT NOT NULL,
                    cwd TEXT,
                    status TEXT NOT NULL,
                    submitted_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    exit_code INTEGER,
                    exit_status TEXT,
                    pid INTEGER,
                    stdout_path TEXT,
                    stderr_path TEXT,
                    error_message TEXT,
                    run_after_id INTEGER
                )
                """
            )
            self._ensure_column(conn, "commands", "pid", "INTEGER")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_commands_status_submitted "
                "ON commands(status, submitted_at DESC, id DESC)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_commands_run_after "
                "ON commands(run_after_id)"
            )

    def recover_interrupted_running_commands(self) -> int:
        with self._lock, self.connect() as conn:
            cur = conn.execute(
                """
                UPDATE commands
                SET status = ?,
                    started_at = NULL,
                    finished_at = NULL,
                    exit_code = NULL,
                    exit_status = 'requeued_after_restart',
                    pid = NULL,
                    error_message = 'CmdDock restarted while command was running.',
                    run_after_id = NULL
                WHERE status = ?
                """,
                (CommandStatus.PENDING, CommandStatus.RUNNING),
            )
            return cur.rowcount

    def create_command(self, command: str, cwd: str | None) -> dict[str, Any]:
        with self._lock, self.connect() as conn:
            submitted_at = utc_now()
            cur = conn.execute(
                """
                INSERT INTO commands (
                    command, cwd, status, submitted_at, run_after_id
                )
                VALUES (?, ?, ?, ?, NULL)
                """,
                (command, cwd, CommandStatus.PENDING, submitted_at),
            )
            return self.get_command(cur.lastrowid, conn=conn)

    def get_command(
        self,
        command_id: int,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, Any]:
        owns_connection = conn is None
        if owns_connection:
            connection_context = self.connect()
            conn = connection_context.__enter__()
        try:
            row = conn.execute("SELECT * FROM commands WHERE id = ?", (command_id,)).fetchone()
            if row is None:
                raise KeyError(f"Command {command_id} does not exist")
            return dict(row)
        finally:
            if owns_connection:
                connection_context.__exit__(None, None, None)

    def list_commands(self, status: CommandStatus | None = None) -> list[dict[str, Any]]:
        with self._lock, self.connect() as conn:
            if status is None:
                rows = conn.execute(
                    "SELECT * FROM commands ORDER BY submitted_at DESC, id DESC"
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT *
                    FROM commands
                    WHERE status = ?
                    ORDER BY submitted_at DESC, id DESC
                    """,
                    (status,),
                ).fetchall()
            return [dict(row) for row in rows]

    def queue_snapshot(self) -> dict[str, list[dict[str, Any]]]:
        return {
            "running": self.list_commands(CommandStatus.RUNNING),
            "pending": self.list_commands(CommandStatus.PENDING),
            "errors": self.list_commands(CommandStatus.ERROR),
        }

    def cancel_pending_command(self, command_id: int) -> dict[str, Any]:
        with self._lock, self.connect() as conn:
            existing = self.get_command(command_id, conn=conn)
            if existing["status"] != CommandStatus.PENDING:
                raise ValueError("Only pending commands can be canceled.")
            conn.execute(
                """
                UPDATE commands
                SET status = ?,
                    finished_at = ?,
                    exit_status = 'canceled',
                    error_message = 'Canceled before execution.'
                WHERE id = ?
                """,
                (CommandStatus.CANCELED, utc_now(), command_id),
            )
            return self.get_command(command_id, conn=conn)

    def retry_error_command(self, command_id: int) -> dict[str, Any]:
        with self._lock, self.connect() as conn:
            existing = self.get_command(command_id, conn=conn)
            if existing["status"] != CommandStatus.ERROR:
                raise ValueError("Only error commands can be retried.")
            conn.execute(
                """
                UPDATE commands
                SET status = ?,
                    started_at = NULL,
                    finished_at = NULL,
                    exit_code = NULL,
                    exit_status = NULL,
                    pid = NULL,
                    error_message = NULL,
                    run_after_id = NULL
                WHERE id = ?
                """,
                (CommandStatus.PENDING, command_id),
            )
            return self.get_command(command_id, conn=conn)

    def claim_next_pending_command(self) -> dict[str, Any] | None:
        with self._lock, self.connect() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM commands
                WHERE status = ?
                ORDER BY
                    CASE WHEN run_after_id IS NULL THEN 1 ELSE 0 END ASC,
                    run_after_id ASC,
                    submitted_at ASC,
                    id ASC
                LIMIT 1
                """,
                (CommandStatus.PENDING,),
            ).fetchone()
            if row is None:
                return None

            command_id = row["id"]
            conn.execute(
                """
                UPDATE commands
                SET status = ?,
                    started_at = ?,
                    finished_at = NULL,
                    exit_code = NULL,
                    exit_status = NULL,
                    pid = NULL,
                    error_message = NULL,
                    run_after_id = NULL
                WHERE id = ? AND status = ?
                """,
                (CommandStatus.RUNNING, utc_now(), command_id, CommandStatus.PENDING),
            )
            return self.get_command(command_id, conn=conn)

    def mark_succeeded(self, command_id: int, exit_code: int) -> dict[str, Any]:
        return self._finish(command_id, CommandStatus.SUCCEEDED, exit_code, "succeeded", None)

    def mark_error(
        self,
        command_id: int,
        exit_code: int | None,
        exit_status: str,
        error_message: str | None,
    ) -> dict[str, Any]:
        return self._finish(command_id, CommandStatus.ERROR, exit_code, exit_status, error_message)

    def requeue_killed(self, command_id: int, exit_code: int, exit_status: str) -> dict[str, Any]:
        with self._lock, self.connect() as conn:
            conn.execute(
                """
                UPDATE commands
                SET status = ?,
                    finished_at = ?,
                    exit_code = ?,
                    exit_status = ?,
                    pid = NULL,
                    error_message = 'Killed by signal; requeued for immediate retry.',
                    run_after_id = ?
                WHERE id = ?
                """,
                (
                    CommandStatus.PENDING,
                    utc_now(),
                    exit_code,
                    exit_status,
                    command_id,
                    command_id,
                ),
            )
            return self.get_command(command_id, conn=conn)

    def set_log_paths(self, command_id: int, stdout_path: Path, stderr_path: Path) -> None:
        with self._lock, self.connect() as conn:
            conn.execute(
                "UPDATE commands SET stdout_path = ?, stderr_path = ? WHERE id = ?",
                (str(stdout_path), str(stderr_path), command_id),
            )

    def set_running_pid(self, command_id: int, pid: int) -> None:
        with self._lock, self.connect() as conn:
            conn.execute(
                "UPDATE commands SET pid = ? WHERE id = ? AND status = ?",
                (pid, command_id, CommandStatus.RUNNING),
            )

    def get_kill_target(self, command_id: int) -> dict[str, Any]:
        with self._lock, self.connect() as conn:
            existing = self.get_command(command_id, conn=conn)
            if existing["status"] != CommandStatus.RUNNING:
                raise ValueError("Only running commands can be killed.")
            if existing["pid"] is None:
                raise ValueError("Running command does not have a recorded process ID yet.")
            return existing

    def _finish(
        self,
        command_id: int,
        status: CommandStatus,
        exit_code: int | None,
        exit_status: str,
        error_message: str | None,
    ) -> dict[str, Any]:
        with self._lock, self.connect() as conn:
            conn.execute(
                """
                UPDATE commands
                SET status = ?,
                    finished_at = ?,
                    exit_code = ?,
                    exit_status = ?,
                    pid = NULL,
                    error_message = ?,
                    run_after_id = NULL
                WHERE id = ?
                """,
                (status, utc_now(), exit_code, exit_status, error_message, command_id),
            )
            return self.get_command(command_id, conn=conn)

    @staticmethod
    def _ensure_column(
        conn: sqlite3.Connection,
        table_name: str,
        column_name: str,
        column_definition: str,
    ) -> None:
        columns = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        existing_column_names = {column["name"] for column in columns}
        if column_name not in existing_column_names:
            conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_definition}")
