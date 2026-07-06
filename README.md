# GPUDock

GPUDock is a local GPU script scheduler for shared single-machine GPU servers. It accepts validated bash script launches, waits until enough GPUs have stayed below 1% memory usage for the task's required idle window when a task declares `GPU_COUNT`, injects `CUDA_DEVICES` and `GPU_COUNT` for GPU tasks, and runs tasks through task groups.

The scheduling model is intentionally simple:

- new task groups start in `draft`, so submitted commands do not run immediately;
- users arrange the group command order first, then start the whole group;
- commands in the same task group run serially;
- commands in different task groups can run in parallel;
- a group with an `error` command is blocked until that command is retried and succeeds or is canceled.

## Features

- Accept only absolute `.sh` bash script paths, with optional `KEY=value` prefixes.
- Read optional `GPU_COUNT` from the submitted command first, then from the script.
- Run commands without `GPU_COUNT` as ordinary non-GPU tasks.
- Use only GPUs whose memory usage stays below 1% for each task's `min_idle_seconds`.
- Reserve selected GPUs inside GPUDock until each launched task finishes.
- Override the launched script environment with `CUDA_DEVICES=<ids>` and `GPU_COUNT=<n>` for GPU tasks.
- Keep new task groups in a draft state until the user explicitly starts them.
- Reorder pending commands inside a draft group; topmost commands run first.
- Run each task group serially while scheduling different groups in parallel.
- Show a task-group dashboard first, with command details inside each group.
- Create and delete task groups; deletion is allowed only when all group commands succeeded or were canceled.
- Requeue tasks when not enough idle GPUs are available.
- Kill launched tasks by process group. GPUDock sends `SIGTERM` first, then `SIGKILL` if the process group survives.
- Send an email after a script process is successfully started.
- Store task metadata and logs in SQLite.

## Quick Start

```bash
git clone https://github.com/AltriaSetsuna/GPUDock.git
cd GPUDock
uv venv
source .venv/bin/activate
uv sync
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

Submit it from the dashboard by opening a task group and entering either the script's absolute path or a restricted bash launch command:

```bash
GPU_COUNT=2 DATA_PATH=/home/data.json bash /absolute/path/to/train.sh
```

The CLI remains available for automation:

```bash
gpudock create-group qwen-sweep --description "Qwen evaluation sweep"
gpudock add /absolute/path/to/train.sh --group qwen-sweep
gpudock add 'GPU_COUNT=2 DATA_PATH=/home/data.json bash /absolute/path/to/train.sh' --group qwen-sweep --min-idle-seconds 300
gpudock reorder-group 1 2 1
gpudock start-group 1
gpudock groups
gpudock commands --group-id 1
gpudock logs 1
gpudock kill 1
```

The legacy `cmddock` entry point is still installed as an alias, but `gpudock` is the preferred command.

## Visual Dashboard

`gpudock serve` starts both the HTTP API and a local browser dashboard at `/`.

The dashboard lets you:

- create task groups;
- inspect group status, counts, current command, and latest activity;
- open a draft group to submit absolute `.sh` script paths or env-prefixed bash launch commands;
- view queued/running/error tasks separately from succeeded/canceled history;
- move pending commands up or down before launch; active queue order starts at 1 and excludes succeeded/canceled tasks;
- start a prepared task group only after its commands and order are final;
- pause a running task group so no later pending command is claimed;
- view stdout/stderr logs;
- retry, cancel, or kill commands when the command state allows it;
- delete completed or empty task groups.

The same dashboard is also available at:

```text
http://127.0.0.1:8765/ui
```

## Scheduling

GPUDock polls GPU memory with:

```bash
nvidia-smi --query-gpu=index,memory.used,memory.total --format=csv,noheader,nounits
```

A GPU is eligible only when it has stayed below the threshold for the task's required
continuous idle window. The default is 120 seconds, and each task may set
`min_idle_seconds` between `0` and `86400` seconds:

```text
memory.used / memory.total < 0.01
```

When GPUDock assigns GPUs to a task, those GPU IDs are reserved in the scheduler process until that task exits. Concurrent task-group launches therefore cannot all observe the same briefly idle GPU during model startup and launch onto it at the same time.

When the scheduler looks for work:

1. It scans task groups whose execution state is `running`.
2. It skips groups with a running command.
3. It skips groups blocked by an error command.
4. It takes only the top pending command from each runnable group.
5. If the command declares `GPU_COUNT`, it checks for enough unreserved GPUs that stayed below 1% memory usage for that task's `min_idle_seconds`.
6. If that group does not have enough GPUs, the task returns to `pending` with `waiting_for_gpu`, and GPUDock keeps scanning later task groups in the same scheduler pass.
7. If the command does not declare `GPU_COUNT`, it is treated as an ordinary non-GPU task and launches without GPU reservation.
8. It launches the script with `bash`.
9. For GPU tasks, it injects `CUDA_DEVICES` and overrides `GPU_COUNT`.
10. It sends a startup email after the process starts.
11. When the task exits, is killed, or fails to launch, GPUDock releases the reservation.

This is work-conserving: if group `B` needs more GPUs than are currently available but group `C` can run, GPUDock skips `B` for that pass and starts `C` instead of leaving GPUs idle.

## HTTP API

### Create a task group

```bash
curl -X POST http://127.0.0.1:8765/groups \
  -H 'content-type: application/json' \
  -d '{"name": "qwen-sweep", "description": "Qwen evaluation sweep"}'
```

### Submit a script

```bash
curl -X POST http://127.0.0.1:8765/commands \
  -H 'content-type: application/json' \
  -d '{"group_name": "qwen-sweep", "command": "/absolute/path/to/train.sh"}'
```

With environment variables:

```bash
curl -X POST http://127.0.0.1:8765/commands \
  -H 'content-type: application/json' \
  -d '{"group_name": "qwen-sweep", "command": "GPU_COUNT=2 DATA_PATH=/home/data.json bash /absolute/path/to/train.sh"}'
```

With a longer idle window:

```bash
curl -X POST http://127.0.0.1:8765/commands \
  -H 'content-type: application/json' \
  -d '{"group_name": "qwen-sweep", "command": "GPU_COUNT=2 bash /absolute/path/to/train.sh", "min_idle_seconds": 300}'
```

### Arrange and start a task group

```bash
curl -X PATCH http://127.0.0.1:8765/groups/1/commands/order \
  -H 'content-type: application/json' \
  -d '{"command_ids": [3, 1, 2]}'

curl -X POST http://127.0.0.1:8765/groups/1/start
```

Commands can be added and reordered only while the task group is `draft`.

### Query state

```bash
curl http://127.0.0.1:8765/groups
curl http://127.0.0.1:8765/groups/1/commands
curl http://127.0.0.1:8765/commands
curl 'http://127.0.0.1:8765/commands?group_id=1'
curl 'http://127.0.0.1:8765/commands?status=error'
```

Global query endpoints return newest records first. Group command queries return the planned
execution order, with the first command shown at the top.

### Control tasks and groups

```http
POST   /groups/{id}/start
POST   /groups/{id}/pause
PATCH  /groups/{id}/commands/order
DELETE /groups/{id}
POST   /commands/{id}/cancel
POST   /commands/{id}/retry
POST   /commands/{id}/kill
GET    /commands/{id}/logs
```

Task groups can be deleted only after every command in the group is `succeeded` or `canceled`.

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
draft group -> running group
running group -> paused group
pending -> running -> succeeded
pending -> running -> error
pending -> canceled
running -> killed -> pending + paused group
running -> canceled_before_launch -> canceled
running -> waiting_for_gpu -> pending
```

Important behavior:

- Exit code `0` becomes `succeeded`.
- New commands stay pending in a draft group until the group is started.
- Pending commands can be reordered only while their task group is draft.
- Non-zero self exit becomes `error` and blocks later commands in the same task group.
- Retrying an error command moves it back to `pending`.
- Pending commands can be canceled.
- Running commands can be killed with `gpudock kill <id>`.
- Killed launched commands receive `SIGTERM` as a process group, followed by `SIGKILL` if needed, so child processes started by the bash script are targeted too.
- Killed launched commands return to `pending`, keep priority within their task group, and pause the whole task group so they are not immediately rescheduled.
- Running commands that have not launched a subprocess yet can be killed; they are marked `canceled` with `exit_status = canceled_before_launch`.
- Insufficient stable-idle GPUs return commands to `pending` with `exit_status = waiting_for_gpu`.
- GPU tasks use `min_idle_seconds` as their required continuous idle window; default `120`, max `86400`.

## Development

```bash
python -m venv .venv
source .venv/bin/activate
uv pip install -e ".[dev]"
pytest
ruff check --no-cache .
```

## Version

Current version: `0.4.0`

## License

MIT
