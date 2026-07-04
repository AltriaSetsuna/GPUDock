# CmdDock Design

CmdDock is intentionally small: one SQLite database, one API process, and one serial worker.

## Goals

- Local-first command submission and monitoring.
- Strict serial execution.
- Durable queue state across restarts.
- Clear distinction between killed commands and commands that failed by themselves.
- Reverse chronological query results.

## Components

### API

The FastAPI application exposes endpoints to submit commands, inspect queue state, view logs, cancel pending commands, and retry error commands.

### SQLite database

SQLite stores command metadata and lifecycle state. It is sufficient for single-machine use and avoids a separate service dependency.

### Worker

The worker claims one pending command at a time, executes it, and records the result. Only one worker should run against a queue if strict serial execution is required.

When a command starts, the worker records the subprocess PID. CmdDock launches each command in a new process session, so the API and CLI can terminate the whole process group for a running command.

## Ordering Rules

Execution order is oldest pending first, except killed commands are requeued with `run_after_id` pointing at themselves. This makes a killed command the next command claimed by the worker.

Query order is always newest first:

- `GET /commands`
- `GET /queue`
- `GET /commands?status=...`
- CLI list commands
- CLI queue and error views

## Failure Semantics

CmdDock distinguishes two cases:

1. The process exits by itself with a non-zero exit code.
   - The command moves to `error`.
   - It will not run again unless manually retried.

2. The process is killed by signal.
   - The command moves back to `pending`.
   - It is prioritized to run before other pending commands.
   - The same command is the next command claimed by the worker.

On daemon restart, commands left in `running` are moved back to `pending`. This avoids silently losing work after a crash or machine restart.
