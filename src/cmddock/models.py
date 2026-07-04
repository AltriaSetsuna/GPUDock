from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class CommandStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    ERROR = "error"
    CANCELED = "canceled"


class QueueMode(StrEnum):
    SERIAL = "serial"
    PARALLEL = "parallel"


class CommandCreate(BaseModel):
    command: str = Field(min_length=1)
    cwd: str | None = None
    queue: QueueMode = QueueMode.SERIAL


class CommandRecord(BaseModel):
    id: int
    command: str
    cwd: str | None
    queue: QueueMode
    status: CommandStatus
    submitted_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    exit_code: int | None
    exit_status: str | None
    pid: int | None
    gpu_count: int | None
    assigned_gpu_ids: str | None
    stdout_path: str | None
    stderr_path: str | None
    error_message: str | None
    run_after_id: int | None


class CommandList(BaseModel):
    commands: list[CommandRecord]


class QueueSnapshot(BaseModel):
    running: list[CommandRecord]
    pending: list[CommandRecord]
    errors: list[CommandRecord]
    serial: list[CommandRecord]
    parallel: list[CommandRecord]


class CommandLogs(BaseModel):
    id: int
    stdout: str
    stderr: str
