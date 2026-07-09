# GPUDock

GPUDock is a local GPU script scheduler for shared GPU environments. It accepts validated bash script launches, waits until enough GPUs have stayed below 1% memory usage for the task's required idle window when a task declares `GPU_COUNT`, injects `CUDA_DEVICES` and `GPU_COUNT` for GPU tasks, and runs tasks through task groups. Commands always run on the local machine; GPUDock can also monitor remote GPU hosts when a local command is expected to use GPUs through a remote service such as vLLM.

The scheduling model is intentionally simple:

- new task groups start in `draft`, so submitted commands do not run immediately;
- task groups have an explicit dashboard order that also defines scheduling priority;
- users arrange the group command order first, then start the whole group;
- commands in the same task group run serially;
- commands in different task groups can run in parallel;
- a group with an `error` command is blocked until that command is retried and succeeds or is canceled.

## Features

- Accept only absolute `.sh` bash script paths, with optional `KEY=value` prefixes.
- Read optional `GPU_COUNT` from the submitted command first, then from the script.
- Run commands without `GPU_COUNT` as ordinary non-GPU tasks.
- Monitor local GPUs by default, or remote GPU hosts selected by configured environment variables such as `VLLM_TARGET`.
- Use only GPUs whose memory usage stays below 1% for each task's `min_idle_seconds`.
- Reserve selected GPUs inside GPUDock per GPU resource, for example `local:0` or `node1:0`, until each launched task finishes.
- Override the launched script environment with `CUDA_DEVICES=<ids>` and `GPU_COUNT=<n>` for GPU tasks.
- Keep new task groups in a draft state until the user explicitly starts them.
- Reorder task groups from the dashboard; higher groups are considered first by the scheduler.
- Reorder pending commands inside a draft group; topmost commands run first.
- Run each task group serially while scheduling different groups in parallel.
- Show a task-group dashboard first, with command details inside each group.
- Show local and remote GPU snapshots in the dashboard's GPU Status panel.
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

For local daily use, install the `gpudock` command into `~/.local/bin`:

```bash
source ./install.sh
gpudock serve
gpudock status
```

`install.sh` creates or reuses `.venv`, installs GPUDock editable with `uv pip`, writes a
`~/.local/bin/gpudock` wrapper, and adds `~/.local/bin` to `~/.bashrc` so the command works in
new terminals. Use `source ./install.sh` when you also want the current terminal to pick up the
command immediately. If you run `./install.sh` normally, run the printed `export PATH=...` line once
in that terminal. Remove the wrapper and managed shell block with:

```bash
./uninstall.sh
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

## Multi-Host GPU Monitoring

By default, GPUDock monitors local GPUs. If a local command uses a remote GPU service, configure remote GPU hosts in `.cmddock/gpu_hosts.conf` or pass a custom file with `--gpu-hosts-config`:

```text
Host node1
  HostName 10.75.76.2
  User yijiali
  Port 22
  IdentityFile ~/.ssh/node1_rsa

RemoteEnv VLLM_TARGET
```

`RemoteEnv VLLM_TARGET` means GPUDock treats the value of `VLLM_TARGET` as a configured host alias. This command still launches locally, but GPUDock checks and reserves GPUs on `node1`:

```bash
VLLM_TARGET=node1 GPU_COUNT=2 bash /absolute/path/to/run_vllm_eval.sh
```

To add another cross-server selector, add another `RemoteEnv` line. The one-argument form treats the environment value as the host alias:

```text
Host node2
  HostName 10.75.76.3
  User yijiali
  Port 22
  IdentityFile ~/.ssh/node2_rsa

RemoteEnv REMOTE_GPU_TARGET
```

Then this command monitors `node2` while still running locally:

```bash
REMOTE_GPU_TARGET=node2 GPU_COUNT=1 bash /absolute/path/to/job.sh
```

You can also map a specific environment value to a host alias when the variable value is not itself a host name:

```text
Host node1
  HostName 10.75.76.2
  User yijiali

RemoteEnv VLLM_TARGET serve-a node1
RemoteEnv SERVICE_TARGET serve-b node2
```

Then `VLLM_TARGET=serve-a bash /absolute/path/to/job.sh` monitors `node1`, and `SERVICE_TARGET=serve-b bash /absolute/path/to/job.sh` monitors `node2`. GPUDock reads environment assignments from the submitted command first, then static assignments in the script, and can also read vLLM target defaults from a referenced `config/vllm_hosts.env`. If no configured remote environment variable is present, the task uses `local`.

If one command matches more than one remote host, GPUDock rejects it instead of guessing which GPU resource to use.

Remote GPU polling uses SSH only for `nvidia-smi`; script execution remains local.

The legacy `cmddock` entry point is still installed as an alias, but `gpudock` is the preferred command.

## Visual Dashboard

`gpudock serve` starts both the HTTP API and a local browser dashboard at `/`.

If port `8765` is busy, `gpudock serve` automatically chooses an available local port and records
it in the service state file. Use `gpudock status` to check the active PID, port, and dashboard URL.
If GPUDock is already running for the same state directory, another `gpudock serve` prints the
existing service URL instead of starting a second scheduler.

The dashboard lets you:

- create task groups;
- move task groups up or down in the dashboard;
- inspect group status, counts, current command, and latest activity;
- open a draft or completed group to submit absolute `.sh` script paths or env-prefixed bash launch commands;
- view queued/running/error tasks separately from succeeded/canceled history;
- move pending commands up or down before launch; active queue order starts at 1 and excludes succeeded/canceled tasks;
- start a prepared task group only after its commands and order are final;
- pause a running task group so no later pending command is claimed;
- inspect local and remote `gpustat -i` output from the GPU Status panel below Create Group;
- view stdout/stderr logs;
- retry, cancel, or kill commands when the command state allows it;
- delete completed or empty task groups.

The GPU Status panel lists resources such as `local` and configured hosts such as `node1`. When switching between resources, the panel shows a loading message for the newly selected resource and ignores stale responses from older requests, so it never renders one host's GPU output under another host's label.

Task Groups shows a loading message until the first `/groups` request completes. If that request fails, the dashboard shows the error instead of silently waiting for the next refresh interval.

The same dashboard is also available at:

```text
http://127.0.0.1:8765/ui
```

## Scheduling

GPUDock polls GPU memory on the selected GPU resource with:

```bash
nvidia-smi --query-gpu=index,memory.used,memory.total --format=csv,noheader,nounits
```

A GPU is eligible only when it has stayed below the threshold for the task's required
continuous idle window. The default is 120 seconds, and each task may set
`min_idle_seconds` between `0` and `86400` seconds:

```text
memory.used / memory.total < 0.01
```

When GPUDock assigns GPUs to a task, those GPU IDs are reserved in the scheduler process until that task exits. Reservations are keyed by resource, so `local:0` and `node1:0` are independent GPUs. Concurrent task-group launches therefore cannot all observe the same briefly idle GPU during model startup and launch onto it at the same time.

When the scheduler looks for work:

1. It scans task groups whose execution state is `running`.
2. It skips groups with a running command.
3. It skips groups blocked by an error command.
4. It takes only the top pending command from each runnable group.
5. It resolves the GPU resource from configured remote environment variables, or uses `local`.
6. If the command declares `GPU_COUNT`, it checks for enough unreserved GPUs on that resource that stayed below 1% memory usage for that task's `min_idle_seconds`.
7. If that group does not have enough GPUs, the task returns to `pending` with `waiting_for_gpu`, and GPUDock keeps scanning later task groups in the same scheduler pass.
8. If the command does not declare `GPU_COUNT`, it is treated as an ordinary non-GPU task and launches without GPU reservation.
9. It launches the script with `bash` on the local machine.
10. For GPU tasks, it injects local ordinal `CUDA_DEVICES` values for the selected resource and overrides `GPU_COUNT`.
11. It sends a startup email after the process starts.
12. When the task exits, is killed, or fails to launch, GPUDock releases the reservation.

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

For remote GPU monitoring through `VLLM_TARGET`:

```bash
curl -X POST http://127.0.0.1:8765/commands \
  -H 'content-type: application/json' \
  -d '{"group_name": "qwen-sweep", "command": "VLLM_TARGET=node1 GPU_COUNT=2 bash /absolute/path/to/run_eval.sh"}'
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
PATCH  /groups/order
PATCH  /groups/{id}/commands/order
DELETE /groups/{id}
POST   /commands/{id}/cancel
POST   /commands/{id}/retry
POST   /commands/{id}/kill
GET    /commands/{id}/logs
```

Task group names are unique. Task groups can be deleted only after every command in the group is `succeeded` or `canceled`.

## Email

Startup email behavior follows `/home/yijiali/python.py`, but credentials and addresses are never hardcoded. Configure email with environment variables:

```bash
export GPUDOCK_EMAIL_RECEIVER="you@example.com"
export GPUDOCK_EMAIL_SENDER="sender@example.com"
export GPUDOCK_EMAIL_PASSWORD="smtp-auth-code"
export GPUDOCK_SMTP_SERVER="smtp.qq.com"
export GPUDOCK_SMTP_PORT="465"
```

If receiver, sender, password, or SMTP server is missing, email is skipped.

## Lifecycle

```text
draft group -> running group
running group -> paused group
pending -> running -> succeeded
pending -> running -> error
pending -> canceled
running -> killed -> pending + paused group
running -> killed_before_launch -> pending + paused group
running -> waiting_for_gpu -> pending
```

Important behavior:

- Exit code `0` becomes `succeeded`.
- New commands stay pending in a draft group until the group is started.
- Completed groups can accept new commands; after submission, the group returns to `draft`
  and must be started manually.
- Pending commands can be reordered only while their task group is draft.
- Non-zero self exit becomes `error` and blocks later commands in the same task group.
- Retrying an error command moves it back to `pending`, pauses the task group, and requires a manual group start before scheduling.
- Pending commands can be canceled.
- Running commands can be killed with `gpudock kill <id>`.
- Killed launched commands receive `SIGTERM` as a process group, followed by `SIGKILL` if needed, so child processes started by the bash script are targeted too.
- Killed launched commands return to `pending`, keep priority within their task group, and pause the whole task group so they are not immediately rescheduled.
- Retrying a killed pending command clears its killed state and marks the task group as requiring a manual restart; the user must start the task group manually.
- Running commands that have not launched a subprocess yet can be killed; they return to `pending` with `exit_status = killed_before_launch`, pause the task group, and require a manual group start before scheduling.
- Insufficient stable-idle GPUs return commands to `pending` with `exit_status = waiting_for_gpu`.
- GPU tasks use `min_idle_seconds` as their required continuous idle window; default `120`, max `86400`.

## Development

```bash
uv venv
source .venv/bin/activate
uv pip install -e ".[dev]"
pytest
ruff check --no-cache .
```

## Version

Current version: `0.5.0`

## License

MIT
