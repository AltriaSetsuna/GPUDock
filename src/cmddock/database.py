from __future__ import annotations

import sqlite3
import threading
from collections.abc import Callable, Iterable
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cmddock.models import CommandStatus, GroupExecutionState, GroupStatus
from cmddock.scheduling import DEFAULT_MIN_IDLE_SECONDS, normalize_min_idle_seconds

DEFAULT_GROUP_NAME = "default"


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
                CREATE TABLE IF NOT EXISTS task_groups (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    description TEXT,
                    created_at TEXT NOT NULL,
                    archived_at TEXT,
                    execution_state TEXT NOT NULL DEFAULT 'draft'
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS commands (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    group_id INTEGER,
                    position INTEGER NOT NULL DEFAULT 0,
                    command TEXT NOT NULL,
                    cwd TEXT,
                    status TEXT NOT NULL,
                    submitted_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    exit_code INTEGER,
                    exit_status TEXT,
                    pid INTEGER,
                    gpu_count INTEGER,
                    min_idle_seconds INTEGER NOT NULL DEFAULT 120,
                    assigned_gpu_ids TEXT,
                    stdout_path TEXT,
                    stderr_path TEXT,
                    error_message TEXT,
                    run_after_id INTEGER,
                    FOREIGN KEY(group_id) REFERENCES task_groups(id)
                )
                """
            )
            self._ensure_column(
                conn,
                "task_groups",
                "execution_state",
                "TEXT NOT NULL DEFAULT 'draft'",
            )
            self._ensure_column(conn, "commands", "group_id", "INTEGER")
            self._ensure_column(conn, "commands", "position", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn, "commands", "pid", "INTEGER")
            self._ensure_column(conn, "commands", "gpu_count", "INTEGER")
            self._ensure_column(
                conn,
                "commands",
                "min_idle_seconds",
                f"INTEGER NOT NULL DEFAULT {DEFAULT_MIN_IDLE_SECONDS}",
            )
            self._ensure_column(conn, "commands", "assigned_gpu_ids", "TEXT")
            default_group_id = self._ensure_group(conn, DEFAULT_GROUP_NAME, "Default task group.")
            conn.execute(
                "UPDATE commands SET group_id = ? WHERE group_id IS NULL",
                (default_group_id,),
            )
            self._backfill_command_positions(conn)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_commands_status_submitted "
                "ON commands(status, submitted_at DESC, id DESC)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_commands_group_status "
                "ON commands(group_id, status, position ASC, id ASC)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_commands_group_position "
                "ON commands(group_id, position ASC, id ASC)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_commands_run_after "
                "ON commands(run_after_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_task_groups_archived "
                "ON task_groups(archived_at, created_at DESC, id DESC)"
            )

    def create_task_group(
        self,
        name: str,
        description: str | None = None,
    ) -> dict[str, Any]:
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("Task group name cannot be empty.")
        with self._lock, self.connect() as conn:
            created_at = utc_now()
            try:
                cur = conn.execute(
                    """
                    INSERT INTO task_groups (
                        name, description, created_at, archived_at, execution_state
                    )
                    VALUES (?, ?, ?, NULL, ?)
                    """,
                    (clean_name, description, created_at, GroupExecutionState.DRAFT),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError(f"Task group '{clean_name}' already exists.") from exc
            return self.get_task_group(cur.lastrowid, conn=conn)

    def get_or_create_task_group(
        self,
        name: str,
        description: str | None = None,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, Any]:
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("Task group name cannot be empty.")
        owns_connection = conn is None
        if owns_connection:
            connection_context = self.connect()
            conn = connection_context.__enter__()
        try:
            row = conn.execute(
                "SELECT id FROM task_groups WHERE name = ?",
                (clean_name,),
            ).fetchone()
            if row is not None:
                group = self.get_task_group(row["id"], conn=conn)
                if group["archived_at"] is not None:
                    raise ValueError(f"Task group '{clean_name}' is archived.")
                return group
            group_id = self._ensure_group(conn, clean_name, description)
            return self.get_task_group(group_id, conn=conn)
        finally:
            if owns_connection:
                connection_context.__exit__(None, None, None)

    def get_task_group(
        self,
        group_id: int,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, Any]:
        groups = self.list_task_groups(include_archived=True, conn=conn)
        for group in groups:
            if group["id"] == group_id:
                return group
        raise KeyError(f"Task group {group_id} does not exist")

    def list_task_groups(
        self,
        include_archived: bool = False,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> list[dict[str, Any]]:
        owns_connection = conn is None
        if owns_connection:
            connection_context = self.connect()
            conn = connection_context.__enter__()
        try:
            archive_filter = "" if include_archived else "WHERE g.archived_at IS NULL"
            rows = conn.execute(
                f"""
                SELECT
                    g.id,
                    g.name,
                    g.description,
                    g.created_at,
                    g.archived_at,
                    g.execution_state,
                    COUNT(c.id) AS total_count,
                    SUM(CASE WHEN c.status = 'pending' THEN 1 ELSE 0 END) AS pending_count,
                    SUM(CASE WHEN c.status = 'running' THEN 1 ELSE 0 END) AS running_count,
                    SUM(CASE WHEN c.status = 'succeeded' THEN 1 ELSE 0 END) AS succeeded_count,
                    SUM(CASE WHEN c.status = 'error' THEN 1 ELSE 0 END) AS error_count,
                    SUM(CASE WHEN c.status = 'canceled' THEN 1 ELSE 0 END) AS canceled_count,
                    MAX(COALESCE(c.finished_at, c.started_at, c.submitted_at, g.created_at))
                        AS latest_activity_at
                FROM task_groups g
                LEFT JOIN commands c ON c.group_id = g.id
                {archive_filter}
                GROUP BY g.id
                ORDER BY latest_activity_at DESC, g.created_at DESC, g.id DESC
                """
            ).fetchall()
            return [self._format_group(dict(row), conn=conn) for row in rows]
        finally:
            if owns_connection:
                connection_context.__exit__(None, None, None)

    def delete_task_group(self, group_id: int) -> dict[str, Any]:
        with self._lock, self.connect() as conn:
            group = self.get_task_group(group_id, conn=conn)
            if group["archived_at"] is not None:
                return group
            blockers = conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM commands
                WHERE group_id = ?
                  AND status NOT IN (?, ?)
                """,
                (group_id, CommandStatus.SUCCEEDED, CommandStatus.CANCELED),
            ).fetchone()["count"]
            if blockers:
                raise ValueError(
                    "Task group can only be deleted after all commands succeeded or canceled."
                )
            conn.execute(
                "UPDATE task_groups SET archived_at = ? WHERE id = ?",
                (utc_now(), group_id),
            )
            return self.get_task_group(group_id, conn=conn)

    def start_task_group(self, group_id: int) -> dict[str, Any]:
        with self._lock, self.connect() as conn:
            group = self.get_task_group(group_id, conn=conn)
            if group["archived_at"] is not None:
                raise ValueError("Cannot start an archived task group.")
            if group["error_count"]:
                raise ValueError("Cannot start a task group with error commands.")
            if group["pending_count"] == 0:
                raise ValueError("Cannot start a task group with no pending commands.")
            conn.execute(
                "UPDATE task_groups SET execution_state = ? WHERE id = ?",
                (GroupExecutionState.RUNNING, group_id),
            )
            return self.get_task_group(group_id, conn=conn)

    def pause_task_group(self, group_id: int) -> dict[str, Any]:
        with self._lock, self.connect() as conn:
            group = self.get_task_group(group_id, conn=conn)
            if group["archived_at"] is not None:
                raise ValueError("Cannot pause an archived task group.")
            conn.execute(
                "UPDATE task_groups SET execution_state = ? WHERE id = ?",
                (GroupExecutionState.PAUSED, group_id),
            )
            return self.get_task_group(group_id, conn=conn)

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
                    assigned_gpu_ids = NULL,
                    error_message = 'GPUDock restarted while command was running.',
                    run_after_id = NULL
                WHERE status = ?
                """,
                (CommandStatus.PENDING, CommandStatus.RUNNING),
            )
            return cur.rowcount

    def create_command(
        self,
        command: str,
        cwd: str | None,
        group_id: int | None = None,
        gpu_count: int | None = None,
        group_name: str | None = None,
        min_idle_seconds: int | None = DEFAULT_MIN_IDLE_SECONDS,
    ) -> dict[str, Any]:
        with self._lock, self.connect() as conn:
            normalized_min_idle_seconds = normalize_min_idle_seconds(min_idle_seconds)
            if group_id is not None and group_name is not None:
                raise ValueError("Use either group_id or group_name, not both.")
            if group_id is None:
                target_group = self.get_or_create_task_group(
                    group_name or DEFAULT_GROUP_NAME,
                    conn=conn,
                )
                group_id = target_group["id"]
            else:
                target_group = self.get_task_group(group_id, conn=conn)
                if target_group["archived_at"] is not None:
                    raise ValueError("Cannot add commands to an archived task group.")
            if target_group["execution_state"] != GroupExecutionState.DRAFT:
                raise ValueError("Commands can only be added while the task group is draft.")
            submitted_at = utc_now()
            position = self._next_command_position(conn, group_id)
            cur = conn.execute(
                """
                INSERT INTO commands (
                    group_id, position, command, cwd, status, submitted_at, gpu_count,
                    min_idle_seconds, run_after_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    group_id,
                    position,
                    command,
                    cwd,
                    CommandStatus.PENDING,
                    submitted_at,
                    gpu_count,
                    normalized_min_idle_seconds,
                ),
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
            row = conn.execute(
                """
                SELECT c.*, g.name AS group_name
                FROM commands c
                JOIN task_groups g ON g.id = c.group_id
                WHERE c.id = ?
                """,
                (command_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"Command {command_id} does not exist")
            return self._format_command(dict(row))
        finally:
            if owns_connection:
                connection_context.__exit__(None, None, None)

    def list_commands(
        self,
        status: CommandStatus | None = None,
        group_id: int | None = None,
        include_archived_groups: bool = False,
    ) -> list[dict[str, Any]]:
        with self._lock, self.connect() as conn:
            clauses = []
            params: list[Any] = []
            if status is not None:
                clauses.append("c.status = ?")
                params.append(status)
            if group_id is not None:
                clauses.append("c.group_id = ?")
                params.append(group_id)
            if not include_archived_groups:
                clauses.append("g.archived_at IS NULL")
            where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
            order_clause = (
                "c.position ASC, c.id ASC"
                if group_id is not None
                else "c.submitted_at DESC, c.id DESC"
            )
            rows = conn.execute(
                f"""
                SELECT c.*, g.name AS group_name
                FROM commands c
                JOIN task_groups g ON g.id = c.group_id
                {where}
                ORDER BY {order_clause}
                """,
                params,
            ).fetchall()
            return [self._format_command(dict(row)) for row in rows]

    def reorder_pending_commands(
        self,
        group_id: int,
        command_ids: list[int],
    ) -> list[dict[str, Any]]:
        with self._lock, self.connect() as conn:
            group = self.get_task_group(group_id, conn=conn)
            if group["archived_at"] is not None:
                raise ValueError("Cannot reorder an archived task group.")
            if group["execution_state"] != GroupExecutionState.DRAFT:
                raise ValueError("Commands can only be reordered while the task group is draft.")
            if len(command_ids) != len(set(command_ids)):
                raise ValueError("Command order contains duplicate command IDs.")
            rows = conn.execute(
                """
                SELECT id
                FROM commands
                WHERE group_id = ?
                  AND status = ?
                ORDER BY position ASC, id ASC
                """,
                (group_id, CommandStatus.PENDING),
            ).fetchall()
            pending_ids = {row["id"] for row in rows}
            requested_ids = set(command_ids)
            if requested_ids != pending_ids:
                raise ValueError("Command order must include every pending command in the group.")
            for position, command_id in enumerate(command_ids, start=1):
                conn.execute(
                    "UPDATE commands SET position = ? WHERE id = ? AND group_id = ?",
                    (position, command_id, group_id),
                )
            return [
                self._format_command(dict(row))
                for row in conn.execute(
                    """
                    SELECT c.*, g.name AS group_name
                    FROM commands c
                    JOIN task_groups g ON g.id = c.group_id
                    WHERE c.group_id = ?
                      AND g.archived_at IS NULL
                    ORDER BY c.position ASC, c.id ASC
                    """,
                    (group_id,),
                ).fetchall()
            ]

    def scheduler_snapshot(self) -> dict[str, list[dict[str, Any]]]:
        return {
            "groups": self.list_task_groups(),
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

    def cancel_unlaunched_running_command(self, command_id: int) -> dict[str, Any]:
        with self._lock, self.connect() as conn:
            existing = self.get_command(command_id, conn=conn)
            if existing["status"] != CommandStatus.RUNNING:
                raise ValueError("Only running commands can be canceled before launch.")
            if existing["pid"] is not None:
                raise ValueError("Running command already has a recorded process ID.")
            conn.execute(
                """
                UPDATE commands
                SET status = ?,
                    finished_at = ?,
                    exit_code = NULL,
                    exit_status = 'canceled_before_launch',
                    pid = NULL,
                    assigned_gpu_ids = NULL,
                    error_message = 'Canceled before the subprocess was launched.',
                    run_after_id = NULL
                WHERE id = ? AND status = ? AND pid IS NULL
                """,
                (CommandStatus.CANCELED, utc_now(), command_id, CommandStatus.RUNNING),
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
                    assigned_gpu_ids = NULL,
                    error_message = NULL,
                    run_after_id = NULL
                WHERE id = ?
                """,
                (CommandStatus.PENDING, command_id),
            )
            return self.get_command(command_id, conn=conn)

    def claim_next_pending_command(
        self,
        excluded_group_ids: set[int] | None = None,
    ) -> dict[str, Any] | None:
        with self._lock, self.connect() as conn:
            excluded_group_ids = excluded_group_ids or set()
            excluded_values = sorted(excluded_group_ids)
            excluded_clause = ""
            if excluded_values:
                placeholders = ", ".join("?" for _ in excluded_values)
                excluded_clause = f"AND c.group_id NOT IN ({placeholders})"
            row = conn.execute(
                f"""
                SELECT c.*
                FROM commands c
                JOIN task_groups g ON g.id = c.group_id
                WHERE c.status = ?
                  AND g.archived_at IS NULL
                  AND g.execution_state = ?
                  {excluded_clause}
                  AND NOT EXISTS (
                      SELECT 1
                      FROM commands running
                      WHERE running.group_id = c.group_id
                        AND running.status = ?
                  )
                  AND NOT EXISTS (
                      SELECT 1
                      FROM commands failed
                      WHERE failed.group_id = c.group_id
                        AND failed.status = ?
                  )
                  AND c.id = (
                      SELECT p.id
                      FROM commands p
                      WHERE p.group_id = c.group_id
                        AND p.status = ?
                      ORDER BY
                          CASE WHEN p.run_after_id IS NULL THEN 1 ELSE 0 END ASC,
                          p.run_after_id ASC,
                          p.position ASC,
                          p.id ASC
                      LIMIT 1
                  )
                ORDER BY
                    c.group_id ASC,
                    CASE WHEN c.run_after_id IS NULL THEN 1 ELSE 0 END ASC,
                    c.run_after_id ASC,
                    c.position ASC,
                    c.id ASC
                LIMIT 1
                """,
                [
                    CommandStatus.PENDING,
                    GroupExecutionState.RUNNING,
                    *excluded_values,
                    CommandStatus.RUNNING,
                    CommandStatus.ERROR,
                    CommandStatus.PENDING,
                ],
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
                    assigned_gpu_ids = NULL,
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
            existing = self.get_command(command_id, conn=conn)
            conn.execute(
                """
                UPDATE commands
                SET status = ?,
                    finished_at = ?,
                    exit_code = ?,
                    exit_status = ?,
                    pid = NULL,
                    assigned_gpu_ids = NULL,
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
            conn.execute(
                """
                UPDATE task_groups
                SET execution_state = ?
                WHERE id = ?
                  AND execution_state = ?
                """,
                (
                    GroupExecutionState.PAUSED,
                    existing["group_id"],
                    GroupExecutionState.RUNNING,
                ),
            )
            return self.get_command(command_id, conn=conn)

    def requeue_waiting_for_gpu(self, command_id: int, reason: str) -> dict[str, Any]:
        with self._lock, self.connect() as conn:
            conn.execute(
                """
                UPDATE commands
                SET status = ?,
                    started_at = NULL,
                    finished_at = NULL,
                    exit_code = NULL,
                    exit_status = 'waiting_for_gpu',
                    pid = NULL,
                    assigned_gpu_ids = NULL,
                    error_message = ?,
                    run_after_id = NULL
                WHERE id = ?
                """,
                (CommandStatus.PENDING, reason, command_id),
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

    def set_gpu_requirement(self, command_id: int, gpu_count: int | None) -> None:
        with self._lock, self.connect() as conn:
            conn.execute(
                "UPDATE commands SET gpu_count = ? WHERE id = ?",
                (gpu_count, command_id),
            )

    def set_assigned_gpu_ids(self, command_id: int, assigned_gpu_ids: str) -> None:
        with self._lock, self.connect() as conn:
            conn.execute(
                "UPDATE commands SET assigned_gpu_ids = ? WHERE id = ? AND status = ?",
                (assigned_gpu_ids, command_id, CommandStatus.RUNNING),
            )

    def start_process_if_running(
        self,
        command_id: int,
        assigned_gpu_ids: str | None,
        launch_process: Callable[[], Any],
    ) -> Any | None:
        with self._lock, self.connect() as conn:
            existing = self.get_command(command_id, conn=conn)
            if existing["status"] != CommandStatus.RUNNING:
                return None

            process = launch_process()
            conn.execute(
                """
                UPDATE commands
                SET pid = ?,
                    assigned_gpu_ids = ?
                WHERE id = ? AND status = ?
                """,
                (process.pid, assigned_gpu_ids, command_id, CommandStatus.RUNNING),
            )
            return process

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
                    assigned_gpu_ids = NULL,
                    error_message = ?,
                    run_after_id = NULL
                WHERE id = ?
                """,
                (status, utc_now(), exit_code, exit_status, error_message, command_id),
            )
            return self.get_command(command_id, conn=conn)

    def _format_group(
        self,
        row: dict[str, Any],
        *,
        conn: sqlite3.Connection,
    ) -> dict[str, Any]:
        total_count = row["total_count"] or 0
        running_count = row["running_count"] or 0
        pending_count = row["pending_count"] or 0
        error_count = row["error_count"] or 0
        succeeded_count = row["succeeded_count"] or 0
        canceled_count = row["canceled_count"] or 0
        current = conn.execute(
            """
            SELECT id, command
            FROM commands
            WHERE group_id = ?
              AND status IN ('running', 'pending', 'error')
            ORDER BY
                CASE status
                    WHEN 'running' THEN 0
                    WHEN 'error' THEN 1
                    ELSE 2
                END,
                position ASC,
                id ASC
            LIMIT 1
            """,
            (row["id"],),
        ).fetchone()
        if row["archived_at"] is not None:
            status = GroupStatus.ARCHIVED
        elif total_count == 0:
            status = GroupStatus.EMPTY
        elif row["execution_state"] == GroupExecutionState.DRAFT:
            status = GroupStatus.DRAFT
        elif row["execution_state"] == GroupExecutionState.PAUSED:
            status = GroupStatus.PAUSED
        elif running_count:
            status = GroupStatus.RUNNING
        elif total_count == succeeded_count + canceled_count:
            status = GroupStatus.COMPLETED
        elif error_count:
            status = GroupStatus.BLOCKED
        elif pending_count:
            status = GroupStatus.PENDING
        else:
            status = GroupStatus.PENDING
        return {
            "id": row["id"],
            "name": row["name"],
            "description": row["description"],
            "created_at": row["created_at"],
            "archived_at": row["archived_at"],
            "execution_state": row["execution_state"],
            "status": status,
            "total_count": total_count,
            "pending_count": pending_count,
            "running_count": running_count,
            "succeeded_count": succeeded_count,
            "error_count": error_count,
            "canceled_count": canceled_count,
            "current_command_id": current["id"] if current else None,
            "current_command": current["command"] if current else None,
            "latest_activity_at": row["latest_activity_at"] or row["created_at"],
        }

    @staticmethod
    def _format_command(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row["id"],
            "group_id": row["group_id"],
            "group_name": row["group_name"],
            "position": row["position"],
            "command": row["command"],
            "cwd": row["cwd"],
            "status": row["status"],
            "submitted_at": row["submitted_at"],
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
            "exit_code": row["exit_code"],
            "exit_status": row["exit_status"],
            "pid": row["pid"],
            "gpu_count": row["gpu_count"],
            "min_idle_seconds": row["min_idle_seconds"],
            "assigned_gpu_ids": row["assigned_gpu_ids"],
            "stdout_path": row["stdout_path"],
            "stderr_path": row["stderr_path"],
            "error_message": row["error_message"],
            "run_after_id": row["run_after_id"],
        }

    @staticmethod
    def _ensure_group(
        conn: sqlite3.Connection,
        name: str,
        description: str | None = None,
    ) -> int:
        row = conn.execute("SELECT id FROM task_groups WHERE name = ?", (name,)).fetchone()
        if row is not None:
            return row["id"]
        cur = conn.execute(
            """
            INSERT INTO task_groups (name, description, created_at, archived_at, execution_state)
            VALUES (?, ?, ?, NULL, ?)
            """,
            (name, description, utc_now(), GroupExecutionState.DRAFT),
        )
        return cur.lastrowid

    @staticmethod
    def _next_command_position(conn: sqlite3.Connection, group_id: int) -> int:
        row = conn.execute(
            """
            SELECT COALESCE(MAX(position), 0) + 1 AS next_position
            FROM commands
            WHERE group_id = ?
            """,
            (group_id,),
        ).fetchone()
        return int(row["next_position"])

    @staticmethod
    def _backfill_command_positions(conn: sqlite3.Connection) -> None:
        group_rows = conn.execute("SELECT id FROM task_groups ORDER BY id ASC").fetchall()
        for group in group_rows:
            command_rows = conn.execute(
                """
                SELECT id
                FROM commands
                WHERE group_id = ?
                  AND position <= 0
                ORDER BY submitted_at ASC, id ASC
                """,
                (group["id"],),
            ).fetchall()
            next_position = Database._next_command_position(conn, group["id"])
            for offset, command in enumerate(command_rows):
                conn.execute(
                    "UPDATE commands SET position = ? WHERE id = ?",
                    (next_position + offset, command["id"]),
                )

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
