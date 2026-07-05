# GPUDock

GPUDock is a local GPU script scheduler. It accepts absolute `.sh` bash script paths, optionally prefixed with environment variable assignments and `bash`, waits until enough GPUs have stayed below 1% memory usage for 120 seconds, injects `CUDA_DEVICES` and `GPU_COUNT`, and then launches the script.

It is designed for a shared single-machine GPU server: simple enough to run locally, but strict about what it executes.

## Features

- Accept only absolute `.sh` bash script paths, with optional `KEY=value` prefixes.
- Read `GPU_COUNT` from the submitted command first, then from the script.
- Use only GPUs whose memory usage stays below 1% for 120 seconds.
- Override the launched script environment with `CUDA_DEVICES=<ids>` and `GPU_COUNT=<n>`.
- Execute `serial` tasks one at a time.
- Execute `parallel` tasks by dispatching all pending parallel work.
- Requeue tasks when not enough idle GPUs are available.
- Requeue killed tasks, while self-failed tasks move to `error`.
- Send an email after a script process is successfully started.
- Store task metadata and logs in SQLite.

## Quick Start

```bash
git clone https://github.com/AltriaSetsuna/GPUDock.git
cd gpudock
python -m venv .venv
source .venv/bin/activate
uv pip install -e ".[dev]"
gpudock serve
```

Then open the visual dashboard:

```text
http://127.0.0.1:8765/
```

Example script:

```bash
#!/usr/bin/env bash
export GPU_COUNT=2
python train.py
```

Submit it from the dashboard by entering either the script's absolute path or a
restricted bash launch command:

```bash
GPU_COUNT=2 DATA_PATH=/home/data.json bash /absolute/path/to/train.sh
```

Then choose `serial` or `parallel`.

The CLI remains available for automation:

```bash
gpudock add /absolute/path/to/train.sh
gpudock add 'GPU_COUNT=2 DATA_PATH=/home/data.json bash /absolute/path/to/train.sh'
gpudock add /absolute/path/to/eval.sh --queue parallel
gpudock queue
gpudock logs 1
gpudock kill 1
```

The legacy `cmddock` entry point is still installed as an alias, but `gpudock` is the preferred command.

## Visual Dashboard

`gpudock serve` starts both the HTTP API and a local browser dashboard at `/`.
The dashboard lets you:

- submit absolute `.sh` script paths or env-prefixed bash launch commands;
- choose `serial` or `parallel` scheduling;
- filter tasks by queue and status;
- inspect assigned GPUs and submission time;
- view stdout/stderr logs;
- retry, cancel, or kill tasks when the task state allows it.

The same dashboard is also available at:

```text
http://127.0.0.1:8765/ui
```

## Scheduling

GPUDock polls GPU memory with:

```bash
nvidia-smi --query-gpu=index,memory.used,memory.total --format=csv,noheader,nounits
```

A GPU is eligible only when it has stayed below the threshold for 120 continuous seconds:

```text
memory.used / memory.total < 0.01
```

When a pending task is claimed:

1. GPUDock validates that `command` is either an absolute `.sh` path or optional
   `KEY=value` assignments followed by `bash /absolute/path/to/script.sh`.
2. GPUDock uses submitted `GPU_COUNT=<n>` first; if omitted, it parses the script's
   last `GPU_COUNT=<n>` or `export GPU_COUNT=<n>` assignment.
3. GPUDock checks for at least `n` GPUs that stayed below 1% memory usage for 120 seconds.
4. If enough GPUs are available, it launches the script with `bash`.
5. It injects `CUDA_DEVICES` and overrides `GPU_COUNT`.
6. It sends a startup email after the process starts.
7. If GPUs are insufficient, the task returns to `pending`.

## HTTP API

### Submit a script

```bash
curl -X POST http://127.0.0.1:8765/commands \
  -H 'content-type: application/json' \
  -d '{"command": "/absolute/path/to/train.sh", "queue": "serial"}'
```

With environment variables:

```bash
curl -X POST http://127.0.0.1:8765/commands \
  -H 'content-type: application/json' \
  -d '{"command": "GPU_COUNT=2 DATA_PATH=/home/data.json bash /absolute/path/to/train.sh", "queue": "serial"}'
```

Parallel tasks use the same endpoint:

```bash
curl -X POST http://127.0.0.1:8765/commands \
  -H 'content-type: application/json' \
  -d '{"command": "/absolute/path/to/eval.sh", "queue": "parallel"}'
```

### Query state

```bash
curl http://127.0.0.1:8765/queue
curl http://127.0.0.1:8765/commands
curl 'http://127.0.0.1:8765/commands?queue=parallel'
curl 'http://127.0.0.1:8765/commands?status=error'
```

All query endpoints return newest records first.

### Control tasks

```http
POST /commands/{id}/cancel
POST /commands/{id}/retry
POST /commands/{id}/kill
GET  /commands/{id}/logs
```

## Email

Startup email behavior follows `/home/yijiali/python.py`.

Defaults:

```text
receiver: 1744141921@qq.com
sender:   1744141921@qq.com
server:   smtp.qq.com
port:     465
```

You can override them with environment variables:

```bash
export GPUDOCK_EMAIL_RECEIVER="you@example.com"
export GPUDOCK_EMAIL_SENDER="sender@example.com"
export GPUDOCK_EMAIL_PASSWORD="smtp-auth-code"
export GPUDOCK_SMTP_SERVER="smtp.qq.com"
export GPUDOCK_SMTP_PORT="465"
```

If receiver, sender, or password is missing, email is skipped.

## Lifecycle

```text
pending -> running -> succeeded
pending -> running -> error
pending -> canceled
running -> killed -> pending
running -> waiting_for_gpu -> pending
```

Important behavior:

- Exit code `0` becomes `succeeded`.
- Non-zero self exit becomes `error`.
- Killed tasks return to `pending`.
- Insufficient stable-idle GPUs return to `pending` with `exit_status = waiting_for_gpu`.
- Pending tasks can be canceled.
- Running tasks can be killed with `gpudock kill <id>`.

## Queue Modes

| Queue | Behavior |
| --- | --- |
| `serial` | Claims one pending task at a time. |
| `parallel` | Claims all pending parallel tasks and starts one runner thread per task. |

The default queue is `serial`.

## Development

```bash
python -m venv .venv
source .venv/bin/activate
uv pip install -e ".[dev]"
pytest
ruff check --no-cache .
```

## Version

Current version: `0.3.0`

## License

MIT
