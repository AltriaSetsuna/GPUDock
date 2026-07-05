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
from cmddock.models import CommandStatus, QueueMode
from cmddock.process_control import terminate_process_group
from cmddock.worker import CommandWorker, ParallelDispatcher

app = typer.Typer(
    help="GPUDock: a local GPU script scheduler with serial and parallel execution modes.",
    no_args_is_help=True,
)


@app.command()
def serve(
    host: Annotated[str, typer.Option(help="Bind host.")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Bind port.")] = 8765,
    data_dir: Annotated[Path, typer.Option(help="State directory.")] = Path(".cmddock"),
) -> None:
    """Start the HTTP API and GPU schedulers."""
    settings = build_settings(data_dir=data_dir, host=host, port=port)
    uvicorn.run(build_app(settings), host=settings.host, port=settings.port)


@app.command()
def add(
    command: Annotated[
        str,
        typer.Argument(
            help="Absolute .sh path, optionally prefixed with env assignments and bash.",
        ),
    ],
    cwd: Annotated[Path | None, typer.Option(help="Working directory for the command.")] = None,
    queue: Annotated[QueueMode, typer.Option(help="Execution queue: serial or parallel.")] = (
        QueueMode.SERIAL
    ),
    data_dir: Annotated[Path, typer.Option(help="State directory.")] = Path(".cmddock"),
) -> None:
    """Add a validated GPU script command to the local SQLite queue."""
    settings = build_settings(data_dir=data_dir)
    database = Database(settings.database_path)
    try:
        parsed = parse_submission_command(command)
        gpu_count = parse_gpu_count(command)
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="command") from exc
    record = database.create_command(
        parsed.command,
        str(cwd) if cwd is not None else None,
        queue,
        gpu_count,
    )
    typer.echo(_to_json(record))


@app.command()
def worker(
    data_dir: Annotated[Path, typer.Option(help="State directory.")] = Path(".cmddock"),
) -> None:
    """Run serial and parallel GPU schedulers for the local queue."""
    settings = build_settings(data_dir=data_dir)
    database = Database(settings.database_path)
    command_worker = CommandWorker(database, settings.logs_dir, settings.poll_interval_seconds)
    parallel_dispatcher = ParallelDispatcher(
        database,
        settings.logs_dir,
        settings.poll_interval_seconds,
    )
    command_worker.start()
    parallel_dispatcher.start()
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass
    finally:
        command_worker.stop()
        parallel_dispatcher.stop()


@app.command()
def commands(
    status: Annotated[CommandStatus | None, typer.Option(help="Filter by command status.")] = None,
    queue: Annotated[QueueMode | None, typer.Option(help="Filter by queue mode.")] = None,
    data_dir: Annotated[Path, typer.Option(help="State directory.")] = Path(".cmddock"),
) -> None:
    """List command history, newest first."""
    settings = build_settings(data_dir=data_dir)
    database = Database(settings.database_path)
    typer.echo(_to_json(database.list_commands(status=status, queue=queue)))


@app.command()
def queue(
    data_dir: Annotated[Path, typer.Option(help="State directory.")] = Path(".cmddock"),
) -> None:
    """Show running, pending, and error queues, newest first in each group."""
    settings = build_settings(data_dir=data_dir)
    database = Database(settings.database_path)
    typer.echo(_to_json(database.queue_snapshot()))


@app.command()
def errors(
    data_dir: Annotated[Path, typer.Option(help="State directory.")] = Path(".cmddock"),
) -> None:
    """Show the error queue, newest first."""
    settings = build_settings(data_dir=data_dir)
    database = Database(settings.database_path)
    typer.echo(_to_json(database.list_commands(CommandStatus.ERROR)))


@app.command()
def cancel(
    command_id: Annotated[int, typer.Argument(help="Pending command ID to cancel.")],
    data_dir: Annotated[Path, typer.Option(help="State directory.")] = Path(".cmddock"),
) -> None:
    """Cancel a pending command."""
    settings = build_settings(data_dir=data_dir)
    database = Database(settings.database_path)
    typer.echo(_to_json(database.cancel_pending_command(command_id)))


@app.command()
def retry(
    command_id: Annotated[int, typer.Argument(help="Error command ID to retry.")],
    data_dir: Annotated[Path, typer.Option(help="State directory.")] = Path(".cmddock"),
) -> None:
    """Move an error command back into the pending queue."""
    settings = build_settings(data_dir=data_dir)
    database = Database(settings.database_path)
    typer.echo(_to_json(database.retry_error_command(command_id)))


@app.command()
def kill(
    command_id: Annotated[int, typer.Argument(help="Running command ID to terminate.")],
    data_dir: Annotated[Path, typer.Option(help="State directory.")] = Path(".cmddock"),
) -> None:
    """Terminate a running command process group.

    Commands canceled before subprocess launch are marked canceled. Commands with a
    recorded PID are killed as a process group, including script child processes; the
    worker observes the signal exit and requeues the killed command so it runs next.
    """
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
