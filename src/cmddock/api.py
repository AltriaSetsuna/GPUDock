from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse

from cmddock.config import Settings
from cmddock.database import Database
from cmddock.gpu import parse_gpu_count, parse_submission_command, resolve_gpu_resource
from cmddock.hosts import load_gpu_host_config
from cmddock.models import (
    CommandCreate,
    CommandList,
    CommandLogs,
    CommandOrderUpdate,
    CommandRecord,
    CommandStatus,
    SchedulerSnapshot,
    TaskGroupCreate,
    TaskGroupList,
    TaskGroupOrderUpdate,
    TaskGroupRecord,
)
from cmddock.process_control import terminate_process_group
from cmddock.web import render_index
from cmddock.worker import GroupScheduler


class AppState:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.gpu_host_config = load_gpu_host_config(settings.resolved_gpu_hosts_config_path)
        self.database = Database(settings.database_path)
        self.scheduler = GroupScheduler(
            self.database,
            settings.logs_dir,
            settings.poll_interval_seconds,
            self.gpu_host_config,
        )

    def start_workers(self) -> None:
        self.scheduler.start()

    def stop_workers(self) -> None:
        self.scheduler.stop()

    def wake_workers(self) -> None:
        self.scheduler.wake()


def build_app(settings: Settings) -> FastAPI:
    state = AppState(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.cmddock = state
        state.start_workers()
        try:
            yield
        finally:
            state.stop_workers()

    app = FastAPI(
        title="GPUDock",
        version="0.5.0",
        summary="Local GPU script scheduler with serial task groups",
        lifespan=lifespan,
    )

    def get_state() -> AppState:
        return state

    state_dependency = Depends(get_state)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def index() -> HTMLResponse:
        return HTMLResponse(render_index())

    @app.get("/ui", response_class=HTMLResponse, include_in_schema=False)
    def ui() -> HTMLResponse:
        return HTMLResponse(render_index())

    @app.post("/groups", response_model=TaskGroupRecord, status_code=201)
    def create_group(
        payload: TaskGroupCreate,
        app_state: AppState = state_dependency,
    ) -> dict:
        try:
            return app_state.database.create_task_group(payload.name, payload.description)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/groups", response_model=TaskGroupList)
    def list_groups(
        include_archived: Annotated[bool, Query()] = False,
        app_state: AppState = state_dependency,
    ) -> dict[str, list[dict]]:
        return {
            "groups": app_state.database.list_task_groups(include_archived=include_archived),
        }

    @app.patch("/groups/order", response_model=TaskGroupList)
    def reorder_groups(
        payload: TaskGroupOrderUpdate,
        app_state: AppState = state_dependency,
    ) -> dict[str, list[dict]]:
        try:
            groups = app_state.database.reorder_task_groups(payload.group_ids)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"groups": groups}

    @app.get("/groups/{group_id}", response_model=TaskGroupRecord)
    def get_group(
        group_id: int,
        app_state: AppState = state_dependency,
    ) -> dict:
        try:
            return app_state.database.get_task_group(group_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.delete("/groups/{group_id}", response_model=TaskGroupRecord)
    def delete_group(
        group_id: int,
        app_state: AppState = state_dependency,
    ) -> dict:
        try:
            return app_state.database.delete_task_group(group_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/groups/{group_id}/start", response_model=TaskGroupRecord)
    def start_group(
        group_id: int,
        app_state: AppState = state_dependency,
    ) -> dict:
        try:
            record = app_state.database.start_task_group(group_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return record

    @app.post("/groups/{group_id}/pause", response_model=TaskGroupRecord)
    def pause_group(
        group_id: int,
        app_state: AppState = state_dependency,
    ) -> dict:
        try:
            return app_state.database.pause_task_group(group_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/groups/{group_id}/commands", response_model=CommandList)
    def list_group_commands(
        group_id: int,
        status: Annotated[CommandStatus | None, Query()] = None,
        app_state: AppState = state_dependency,
    ) -> dict[str, list[dict]]:
        try:
            app_state.database.get_task_group(group_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {
            "commands": app_state.database.list_commands(status=status, group_id=group_id),
        }

    @app.patch("/groups/{group_id}/commands/order", response_model=CommandList)
    def reorder_group_commands(
        group_id: int,
        payload: CommandOrderUpdate,
        app_state: AppState = state_dependency,
    ) -> dict[str, list[dict]]:
        try:
            commands = app_state.database.reorder_pending_commands(group_id, payload.command_ids)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"commands": commands}

    @app.post("/commands", response_model=CommandRecord, status_code=201)
    def create_command(
        payload: CommandCreate,
        app_state: AppState = state_dependency,
    ) -> dict:
        try:
            parsed = parse_submission_command(payload.command)
            gpu_count = parse_gpu_count(payload.command)
            gpu_resource = resolve_gpu_resource(payload.command, app_state.gpu_host_config)
            record = app_state.database.create_command(
                parsed.command,
                payload.cwd,
                group_id=payload.group_id,
                gpu_count=gpu_count,
                gpu_resource=gpu_resource,
                group_name=payload.group_name,
                min_idle_seconds=payload.min_idle_seconds,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        app_state.wake_workers()
        return record

    @app.get("/commands", response_model=CommandList)
    def list_commands(
        status: Annotated[CommandStatus | None, Query()] = None,
        group_id: Annotated[int | None, Query()] = None,
        app_state: AppState = state_dependency,
    ) -> dict[str, list[dict]]:
        return {
            "commands": app_state.database.list_commands(status=status, group_id=group_id),
        }

    @app.get("/commands/{command_id}", response_model=CommandRecord)
    def get_command(
        command_id: int,
        app_state: AppState = state_dependency,
    ) -> dict:
        try:
            return app_state.database.get_command(command_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/commands/{command_id}/cancel", response_model=CommandRecord)
    def cancel_command(
        command_id: int,
        app_state: AppState = state_dependency,
    ) -> dict:
        try:
            return app_state.database.cancel_pending_command(command_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/commands/{command_id}/retry", response_model=CommandRecord)
    def retry_command(
        command_id: int,
        app_state: AppState = state_dependency,
    ) -> dict:
        try:
            record = app_state.database.retry_command(command_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return record

    @app.post("/commands/{command_id}/kill", response_model=CommandRecord)
    def kill_command(
        command_id: int,
        app_state: AppState = state_dependency,
    ) -> dict:
        try:
            current = app_state.database.get_command(command_id)
            if current["status"] == CommandStatus.RUNNING and current["pid"] is None:
                return app_state.database.requeue_unlaunched_killed(command_id)
            record = app_state.database.get_kill_target(command_id)
            terminate_process_group(record["pid"])
            return record
        except ProcessLookupError as exc:
            raise HTTPException(
                status_code=409,
                detail="Recorded process is no longer running.",
            ) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/commands/{command_id}/logs", response_model=CommandLogs)
    def get_logs(
        command_id: int,
        app_state: AppState = state_dependency,
    ) -> dict[str, str | int]:
        try:
            record = app_state.database.get_command(command_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        stdout = _read_text_file(record["stdout_path"])
        stderr = _read_text_file(record["stderr_path"])
        return {"id": command_id, "stdout": stdout, "stderr": stderr}

    @app.get("/queue", response_model=SchedulerSnapshot)
    def queue(app_state: AppState = state_dependency) -> dict[str, list[dict]]:
        return app_state.database.scheduler_snapshot()

    return app


def _read_text_file(path_value: str | None) -> str:
    if path_value is None:
        return ""
    path = Path(path_value)
    if not path.exists():
        return ""
    return path.read_text(errors="replace")
