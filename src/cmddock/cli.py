from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Annotated

import typer
import uvicorn

from cmddock.api import build_app
from cmddock.config import build_settings
from cmddock.database import Database
from cmddock.gpu import parse_gpu_count, parse_submission_command
from cmddock.models import CommandStatus
from cmddock.process_control import terminate_process_group
from cmddock.scheduling import (
    DEFAULT_MIN_IDLE_SECONDS,
    MAX_MIN_IDLE_SECONDS,
    normalize_min_idle_seconds,
)
from cmddock.worker import GroupScheduler

app = typer.Typer(
    help="GPUDock: a local GPU script scheduler with serial task groups.",
    no_args_is_help=True,
)


@app.command()
def serve(
    host: Annotated[str, typer.Option(help="Bind host.")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Bind port.")] = 8765,
    data_dir: Annotated[Path, typer.Option(help="State directory.")] = Path(".cmddock"),
) -> None:
    """Start the HTTP API and task-group scheduler."""
    settings = build_settings(data_dir=data_dir, host=host, port=port)
    uvicorn.run(build_app(settings), host=settings.host, port=settings.port)


@app.command("create-group")
def create_group(
    name: Annotated[str, typer.Argument(help="Task group name.")],
    description: Annotated[str | None, typer.Option(help="Optional description.")] = None,
    data_dir: Annotated[Path, typer.Option(help="State directory.")] = Path(".cmddock"),
) -> None:
    """Create a task group."""
    settings = build_settings(data_dir=data_dir)
    database = Database(settings.database_path)
    typer.echo(_to_json(database.create_task_group(name, description)))


@app.command("delete-group")
def delete_group(
    group_id: Annotated[int, typer.Argument(help="Task group ID.")],
    data_dir: Annotated[Path, typer.Option(help="State directory.")] = Path(".cmddock"),
) -> None:
    """Archive a completed task group."""
    settings = build_settings(data_dir=data_dir)
    database = Database(settings.database_path)
    try:
        typer.echo(_to_json(database.delete_task_group(group_id)))
    except (KeyError, ValueError) as exc:
        raise typer.BadParameter(str(exc), param_hint="group_id") from exc


@app.command("start-group")
def start_group(
    group_id: Annotated[int, typer.Argument(help="Task group ID.")],
    data_dir: Annotated[Path, typer.Option(help="State directory.")] = Path(".cmddock"),
) -> None:
    """Start a prepared task group."""
    settings = build_settings(data_dir=data_dir)
    database = Database(settings.database_path)
    try:
        typer.echo(_to_json(database.start_task_group(group_id)))
    except (KeyError, ValueError) as exc:
        raise typer.BadParameter(str(exc), param_hint="group_id") from exc


@app.command("pause-group")
def pause_group(
    group_id: Annotated[int, typer.Argument(help="Task group ID.")],
    data_dir: Annotated[Path, typer.Option(help="State directory.")] = Path(".cmddock"),
) -> None:
    """Pause future claims for a task group."""
    settings = build_settings(data_dir=data_dir)
    database = Database(settings.database_path)
    try:
        typer.echo(_to_json(database.pause_task_group(group_id)))
    except (KeyError, ValueError) as exc:
        raise typer.BadParameter(str(exc), param_hint="group_id") from exc


@app.command("reorder-group")
def reorder_group(
    group_id: Annotated[int, typer.Argument(help="Task group ID.")],
    command_ids: Annotated[
        list[int],
        typer.Argument(help="Pending command IDs in the desired execution order."),
    ],
    data_dir: Annotated[Path, typer.Option(help="State directory.")] = Path(".cmddock"),
) -> None:
    """Replace the pending-command order for a draft task group."""
    settings = build_settings(data_dir=data_dir)
    database = Database(settings.database_path)
    try:
        typer.echo(_to_json(database.reorder_pending_commands(group_id, command_ids)))
    except (KeyError, ValueError) as exc:
        raise typer.BadParameter(str(exc), param_hint="command_ids") from exc


@app.command()
def groups(
    include_archived: Annotated[
        bool,
        typer.Option(help="Include archived task groups."),
    ] = False,
    data_dir: Annotated[Path, typer.Option(help="State directory.")] = Path(".cmddock"),
) -> None:
    """List task groups, newest activity first."""
    settings = build_settings(data_dir=data_dir)
    database = Database(settings.database_path)
    typer.echo(_to_json(database.list_task_groups(include_archived=include_archived)))


@app.command()
def add(
    command: Annotated[
        str,
        typer.Argument(
            help="Absolute .sh path, optionally prefixed with env assignments and bash.",
        ),
    ],
    cwd: Annotated[Path | None, typer.Option(help="Working directory for the command.")] = None,
    group: Annotated[str, typer.Option(help="Task group name.")] = "default",
    group_id: Annotated[int | None, typer.Option(help="Existing task group ID.")] = None,
    min_idle_seconds: Annotated[
        int,
        typer.Option(
            help=f"Required continuous idle seconds for GPU tasks, max {MAX_MIN_IDLE_SECONDS}.",
        ),
    ] = DEFAULT_MIN_IDLE_SECONDS,
    data_dir: Annotated[Path, typer.Option(help="State directory.")] = Path(".cmddock"),
) -> None:
    """Add a validated GPU script command to a task group."""
    settings = build_settings(data_dir=data_dir)
    database = Database(settings.database_path)
    try:
        parsed = parse_submission_command(command)
        gpu_count = parse_gpu_count(command)
        normalized_min_idle_seconds = normalize_min_idle_seconds(min_idle_seconds)
        record = database.create_command(
            parsed.command,
            str(cwd) if cwd is not None else None,
            group_id=group_id,
            gpu_count=gpu_count,
            group_name=None if group_id is not None else group,
            min_idle_seconds=normalized_min_idle_seconds,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="command") from exc
    typer.echo(_to_json(record))


@app.command()
def worker(
    data_dir: Annotated[Path, typer.Option(help="State directory.")] = Path(".cmddock"),
) -> None:
    """Run the task-group GPU scheduler."""
    settings = build_settings(data_dir=data_dir)
    database = Database(settings.database_path)
    scheduler = GroupScheduler(database, settings.logs_dir, settings.poll_interval_seconds)
    scheduler.start()
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass
    finally:
        scheduler.stop()


@app.command()
def commands(
    status: Annotated[CommandStatus | None, typer.Option(help="Filter by command status.")] = None,
    group_id: Annotated[int | None, typer.Option(help="Filter by task group ID.")] = None,
    data_dir: Annotated[Path, typer.Option(help="State directory.")] = Path(".cmddock"),
) -> None:
    """List command history, newest first."""
    settings = build_settings(data_dir=data_dir)
    database = Database(settings.database_path)
    typer.echo(_to_json(database.list_commands(status=status, group_id=group_id)))


@app.command()
def queue(
    data_dir: Annotated[Path, typer.Option(help="State directory.")] = Path(".cmddock"),
) -> None:
    """Show scheduler snapshot grouped by status."""
    settings = build_settings(data_dir=data_dir)
    database = Database(settings.database_path)
    typer.echo(_to_json(database.scheduler_snapshot()))


@app.command()
def errors(
    group_id: Annotated[int | None, typer.Option(help="Filter by task group ID.")] = None,
    data_dir: Annotated[Path, typer.Option(help="State directory.")] = Path(".cmddock"),
) -> None:
    """Show error commands, newest first."""
    settings = build_settings(data_dir=data_dir)
    database = Database(settings.database_path)
    typer.echo(_to_json(database.list_commands(CommandStatus.ERROR, group_id=group_id)))


@app.command()
def cancel(
    command_id: Annotated[int, typer.Argument(help="Pending command ID to cancel.")],
    data_dir: Annotated[Path, typer.Option(help="State directory.")] = Path(".cmddock"),
) -> None:
    """Cancel a pending command."""
    settings = build_settings(data_dir=data_dir)
    database = Database(settings.database_path)
    try:
        typer.echo(_to_json(database.cancel_pending_command(command_id)))
    except (KeyError, ValueError) as exc:
        raise typer.BadParameter(str(exc), param_hint="command_id") from exc


@app.command()
def retry(
    command_id: Annotated[int, typer.Argument(help="Error or killed pending command ID to retry.")],
    data_dir: Annotated[Path, typer.Option(help="State directory.")] = Path(".cmddock"),
) -> None:
    """Move an error or killed pending command back into a clean pending state."""
    settings = build_settings(data_dir=data_dir)
    database = Database(settings.database_path)
    try:
        typer.echo(_to_json(database.retry_command(command_id)))
    except (KeyError, ValueError) as exc:
        raise typer.BadParameter(str(exc), param_hint="command_id") from exc


@app.command()
def kill(
    command_id: Annotated[int, typer.Argument(help="Running command ID to terminate.")],
    data_dir: Annotated[Path, typer.Option(help="State directory.")] = Path(".cmddock"),
) -> None:
    """Terminate a running command process group."""
    settings = build_settings(data_dir=data_dir)
    database = Database(settings.database_path)
    try:
        current = database.get_command(command_id)
        if current["status"] == CommandStatus.RUNNING and current["pid"] is None:
            typer.echo(_to_json(database.cancel_unlaunched_running_command(command_id)))
            return
        record = database.get_kill_target(command_id)
        terminate_process_group(record["pid"])
    except KeyError as exc:
        raise typer.BadParameter(str(exc), param_hint="command_id") from exc
    except ProcessLookupError as exc:
        raise typer.BadParameter(
            "Recorded process is no longer running.",
            param_hint="command_id",
        ) from exc
    except PermissionError as exc:
        raise typer.BadParameter(str(exc), param_hint="command_id") from exc
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="command_id") from exc
    typer.echo(_to_json(record))


@app.command()
def logs(
    command_id: Annotated[int, typer.Argument(help="Command ID.")],
    stream: Annotated[str, typer.Option(help="stdout, stderr, or both.")] = "both",
    data_dir: Annotated[Path, typer.Option(help="State directory.")] = Path(".cmddock"),
) -> None:
    """Print command logs."""
    settings = build_settings(data_dir=data_dir)
    database = Database(settings.database_path)
    record = database.get_command(command_id)
    if stream in {"stdout", "both"}:
        typer.echo(_read_log(record["stdout_path"]), nl=not stream == "both")
    if stream in {"stderr", "both"}:
        typer.echo(_read_log(record["stderr_path"]))


def _read_log(path_value: str | None) -> str:
    if path_value is None:
        return ""
    path = Path(path_value)
    if not path.exists():
        return ""
    return path.read_text(errors="replace")


def _to_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)
