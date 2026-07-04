# CmdDock

CmdDock is a local command queue daemon. It accepts commands, records their lifecycle, and executes them through either a serial queue or a parallel queue.

It is designed for single-machine use: simple enough to run locally, but structured like a maintainable open source project.

## Features

- Submit shell commands through an HTTP API or CLI.
- Execute `serial` commands one at a time with a single background worker.
- Execute `parallel` commands immediately by dispatching all pending parallel work.
- Persist queue state in SQLite.
- Record submission time, finish time, and exit status for every command.
- Requeue killed commands immediately so the killed command runs again next.
- Move commands that exit by themselves with a non-zero status into an error queue.
- Show all query results in reverse chronological order, with newest records first.
- Store stdout and stderr logs per command.
- Terminate a running command and let the worker requeue it automatically.

## Quick Start

```bash
cd /home/yijiali/tools/CmdDock
source .venv/bin/activate
uv pip install -e ".[dev]"
cmddock serve
```

In another terminal:

```bash
cmddock add "echo hello"
cmddock add "python download.py" --queue parallel
cmddock queue
cmddock errors
cmddock logs 1
cmddock kill 1
```

By default, CmdDock listens on `127.0.0.1:8765` and stores state under `.cmddock/`.

## HTTP API

### Submit a command

```bash
curl -X POST http://127.0.0.1:8765/commands \
  -H 'content-type: application/json' \
  -d '{"command": "echo hello", "queue": "serial"}'
```

Parallel commands use the same endpoint:

```bash
curl -X POST http://127.0.0.1:8765/commands \
  -H 'content-type: application/json' \
  -d '{"command": "python download.py", "queue": "parallel"}'
```

### Query queue state

```bash
curl http://127.0.0.1:8765/queue
```

### Query command history

```bash
curl http://127.0.0.1:8765/commands
curl 'http://127.0.0.1:8765/commands?queue=parallel'
curl 'http://127.0.0.1:8765/commands?status=error'
```

All query endpoints return newest records first.

### Control commands

```http
POST /commands/{id}/cancel
POST /commands/{id}/retry
POST /commands/{id}/kill
```

## Command Lifecycle

```text
pending -> running -> succeeded
pending -> running -> error
pending -> canceled
running -> killed -> pending
```

Important behavior:

- A command with exit code `0` becomes `succeeded`.
- A command that exits by itself with a non-zero exit code becomes `error`.
- A killed serial command becomes `pending` again and is scheduled before other serial commands.
- A killed parallel command becomes `pending` again and is dispatched again by the parallel dispatcher.
- A pending command can be canceled.
- A running command can be killed with `cmddock kill <id>` or `POST /commands/{id}/kill`.

## Queue Modes

CmdDock stores all commands in one table and uses the `queue` field to choose the execution strategy.

| Queue | Behavior |
| --- | --- |
| `serial` | Claims one pending command at a time, preserving oldest-first execution order. |
| `parallel` | Claims all pending parallel commands and starts them immediately. |

The default queue is `serial`, so existing usage remains conservative.

## Project Layout

```text
src/cmddock/
├── api.py        # FastAPI routes and app factory
├── cli.py        # Typer command-line interface
├── config.py     # Runtime settings
├── database.py   # SQLite schema and queries
├── models.py     # Pydantic response/request models
├── runner.py     # subprocess execution logic
└── worker.py     # serial worker and parallel dispatcher
```

## Development

```bash
uv pip install -e ".[dev]"
pytest
ruff check .
```

## Version

Current version: `0.2.0`

## License

MIT
