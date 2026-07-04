# CmdDock Design

CmdDock is intentionally small: one SQLite database, one API process, one serial worker, and one parallel dispatcher.

## Goals

- Local-first command submission and monitoring.
- Strict serial execution for commands in the `serial` queue.
- Immediate fan-out execution for commands in the `parallel` queue.
- Durable queue state across restarts.
- Clear distinction between killed commands and commands that failed by themselves.
- Reverse chronological query results.

## Components

### API

The FastAPI application exposes endpoints to submit commands, inspect queue state, view logs, cancel pending commands, and retry error commands.

### SQLite database

SQLite stores command metadata and lifecycle state. It is sufficient for single-machine use and avoids a separate service dependency.

CmdDock keeps one `commands` table and uses `queue` as a scheduling field:

- `serial` means the command is claimed by the serial worker.
- `parallel` means the command is claimed by the parallel dispatcher.

The single-table design keeps history, logs, kill/retry/cancel behavior, and error handling uniform across execution modes.

### Serial Worker

The serial worker claims one pending `serial` command at a time, executes it, and records the result. Only one serial worker should run against a queue if strict serial execution is required.

When a command starts, the worker records the subprocess PID. CmdDock launches each command in a new process session, so the API and CLI can terminate the whole process group for a running command.

### Parallel Dispatcher

The parallel dispatcher repeatedly claims pending `parallel` commands and starts one runner thread for each claimed command. It does not impose a concurrency limit in v0.2.0, so all pending parallel commands are submitted immediately.

The dispatcher uses the same command runner and lifecycle transitions as the serial worker.

## Ordering Rules

Serial execution order is oldest pending first, except killed serial commands are requeued with `run_after_id` pointing at themselves. This makes a killed serial command the next serial command claimed by the worker.

Parallel commands are dispatched as soon as the dispatcher observes them. Killed parallel commands are requeued and dispatched again when the dispatcher wakes.

Query order is always newest first:

- `GET /commands`
- `GET /queue`
- `GET /commands?status=...`
- `GET /commands?queue=...`
- CLI list commands
- CLI queue and error views

## Failure Semantics

CmdDock distinguishes two cases:

1. The process exits by itself with a non-zero exit code.
   - The command moves to `error`.
   - It will not run again unless manually retried.

2. The process is killed by signal.
   - The command moves back to `pending`.
   - Serial commands are prioritized to run before other pending serial commands.
   - Parallel commands are dispatched again by the parallel dispatcher.

On daemon restart, commands left in `running` are moved back to `pending`. This avoids silently losing work after a crash or machine restart.
