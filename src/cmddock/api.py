from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse

from cmddock.config import Settings
from cmddock.database import Database
from cmddock.gpu import parse_gpu_count, parse_submission_command
from cmddock.models import (
    CommandCreate,
    CommandList,
    CommandLogs,
    CommandRecord,
    CommandStatus,
    QueueMode,
    QueueSnapshot,
)
from cmddock.process_control import terminate_process_group
from cmddock.web import render_index
from cmddock.worker import CommandWorker, ParallelDispatcher


class AppState:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.database = Database(settings.database_path)
        self.worker = CommandWorker(
            self.database,
            settings.logs_dir,
            settings.poll_interval_seconds,
        )
        self.parallel_dispatcher = ParallelDispatcher(
            self.database,
            settings.logs_dir,
            settings.poll_interval_seconds,
        )

    def start_workers(self) -> None:
        self.worker.start()
        self.parallel_dispatcher.start()

    def stop_workers(self) -> None:
        self.worker.stop()
        self.parallel_dispatcher.stop()

    def wake_workers(self) -> None:
        self.worker.wake()
        self.parallel_dispatcher.wake()


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
        version="0.3.0",
        summary="Local GPU script scheduler for idle GPUs",
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

    @app.post("/commands", response_model=CommandRecord, status_code=201)
    def create_command(
        payload: CommandCreate,
        app_state: AppState = state_dependency,
    ) -> dict:
        try:
            parsed = parse_submission_command(payload.command)
            gpu_count = parse_gpu_count(payload.command)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        record = app_state.database.create_command(
            parsed.command,
            payload.cwd,
            payload.queue,
            gpu_count,
        )
        app_state.wake_workers()
        return record

    @app.get("/commands", response_model=CommandList)
    def list_commands(
        status: Annotated[CommandStatus | None, Query()] = None,
        queue: Annotated[QueueMode | None, Query()] = None,
        app_state: AppState = state_dependency,
    ) -> dict[str, list[dict]]:
        return {"commands": app_state.database.list_commands(status=status, queue=queue)}

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
            record = app_state.database.retry_error_command(command_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        app_state.wake_workers()
        return record

    @app.post("/commands/{command_id}/kill", response_model=CommandRecord)
    def kill_command(
        command_id: int,
        app_state: AppState = state_dependency,
    ) -> dict:
        try:
            current = app_state.database.get_command(command_id)
            if current["status"] == CommandStatus.RUNNING and current["pid"] is None:
                record = app_state.database.cancel_unlaunched_running_command(command_id)
                app_state.wake_workers()
                return record
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

    @app.get("/queue", response_model=QueueSnapshot)
    def queue(app_state: AppState = state_dependency) -> dict[str, list[dict]]:
        return app_state.database.queue_snapshot()

    return app


def _read_text_file(path_value: str | None) -> str:
    if path_value is None:
        return ""
    path = Path(path_value)
    if not path.exists():
        return ""
    return path.read_text(errors="replace")
