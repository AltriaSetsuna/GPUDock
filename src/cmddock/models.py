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


class GroupStatus(StrEnum):
    DRAFT = "draft"
    EMPTY = "empty"
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class GroupExecutionState(StrEnum):
    DRAFT = "draft"
    RUNNING = "running"
    PAUSED = "paused"


class TaskGroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = None


class TaskGroupRecord(BaseModel):
    id: int
    name: str
    description: str | None
    created_at: datetime
    archived_at: datetime | None
    execution_state: GroupExecutionState
    status: GroupStatus
    total_count: int
    pending_count: int
    running_count: int
    succeeded_count: int
    error_count: int
    canceled_count: int
    current_command_id: int | None
    current_command: str | None
    latest_activity_at: datetime | None


class TaskGroupList(BaseModel):
    groups: list[TaskGroupRecord]


class CommandCreate(BaseModel):
    command: str = Field(min_length=1)
    cwd: str | None = None
    group_id: int | None = None
    group_name: str | None = None


class CommandOrderUpdate(BaseModel):
    command_ids: list[int] = Field(min_length=1)


class CommandRecord(BaseModel):
    id: int
    group_id: int
    group_name: str
    position: int
    command: str
    cwd: str | None
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


class SchedulerSnapshot(BaseModel):
    groups: list[TaskGroupRecord]
    running: list[CommandRecord]
    pending: list[CommandRecord]
    errors: list[CommandRecord]


class CommandLogs(BaseModel):
    id: int
    stdout: str
    stderr: str
