# GPUDock Design

GPUDock is a local scheduler for GPU-backed bash scripts. It constrains execution to validated script files, stable-idle GPU availability, and task-group ordering.

## Goals

- Accept only absolute `.sh` script paths, optionally prefixed with environment assignments.
- Parse `GPU_COUNT` from each submitted command first, then from the script.
- Launch GPU tasks only on GPUs that stay below 1% memory usage for the task's `min_idle_seconds`.
- Reserve assigned GPUs locally until the owning task exits.
- Inject `CUDA_DEVICES` and override `GPU_COUNT` at launch time.
- Keep new task groups in `draft` until the user explicitly starts them.
- Let users reorder pending commands inside a draft group before launch.
- Run commands serially inside each task group.
- Run different task groups concurrently when GPUs are available.
- Block a group after a command fails until the failed command is retried or canceled.
- Requeue tasks that cannot currently acquire enough idle GPUs.
- Send a startup email after the subprocess starts.
- Provide a local visual dashboard for task-group supervision.

## Data Model

GPUDock keeps task groups and commands separate:

- `task_groups`: unique group name, description, dashboard/scheduling position, creation time, archive time, and execution state.
- `commands`: command text, `group_id`, `position`, lifecycle fields, GPU fields, log paths, and retry ordering.

The old `queue` column from earlier versions is ignored if it exists in an upgraded database. New scheduling decisions use only `group_id`.

GPU-specific fields:

- `gpu_count`: parsed from the submitted command or script.
- `min_idle_seconds`: task-specific continuous idle window, default `120`, max `86400`.
- `assigned_gpu_ids`: comma-separated GPU IDs injected as `CUDA_DEVICES`.

Task group status is derived from commands:

- `empty`: no commands.
- `draft`: commands exist, but the group has not been started.
- `running`: at least one command is running.
- `paused`: no new pending command will be claimed until the group is started again.
- `blocked`: at least one command is in `error`.
- `pending`: pending commands remain and the group is not running or blocked.
- `completed`: every command is `succeeded` or `canceled`.
- `archived`: the group was deleted.

Task group execution state is stored separately from derived display status:

- `draft`: commands can be added and reordered, but the scheduler ignores the group.
- `running`: the scheduler may claim the first pending command in the group.
- `paused`: already running commands may finish, but no later pending command is claimed.

## Script Validation

Submissions are rejected unless `command` is:

- an absolute `.sh` file path; or
- optional `KEY=value` assignments followed by optional `bash` and an absolute `.sh` file path.

`GPU_COUNT` is optional. If it is missing from both the submitted command and the
script, GPUDock treats the command as a non-GPU task and does not reserve or inject GPUs.

This intentionally rejects arbitrary shell strings.

Accepted examples:

```bash
/absolute/path/to/train.sh
GPU_COUNT=2 DATA_PATH=/home/data.json bash /absolute/path/to/train.sh
MODEL=llama DATA_PATH=/home/data.json /absolute/path/to/train.sh
```

Rejected examples:

```bash
python train.py
bash train.sh
DATA_PATH=/home/data.json bash /absolute/path/to/train.sh --epochs 3
```

## GPU Selection

GPUDock reads GPU memory usage using `nvidia-smi`:

```bash
nvidia-smi --query-gpu=index,memory.used,memory.total --format=csv,noheader,nounits
```

A GPU is idle only after it has stayed below the threshold for the task's required
continuous idle window. The default is 120 seconds, and `min_idle_seconds` can be
set from `0` to `86400` seconds:

```text
memory.used / memory.total < 0.01
```

GPUDock tracks the first observed low-memory timestamp for each GPU. If a GPU rises back to 1% memory usage or higher, its timer is reset. The stored timestamp is capped so elapsed idle time never grows beyond the configured maximum. This avoids assigning a card that briefly appears free while another process is still starting, shutting down, or between allocation phases.

If a task needs `GPU_COUNT=n`, GPUDock selects the first `n` stable-idle GPU IDs. If fewer than `n` GPUs are idle, the task returns to `pending` with:

```text
exit_status = waiting_for_gpu
```

Selection and reservation happen together under a process-local lock. During model startup, a process may not have allocated visible GPU memory yet, so another runner could otherwise observe the same GPU as idle and start a large task on it. GPUDock keeps selected GPU IDs reserved until the task exits or launch fails.

## Scheduling

The scheduler is group-aware:

1. It scans groups by their explicit `task_groups.position` order.
2. It looks for groups whose execution state is `running`.
3. It skips any group that has an error command.
4. It chooses the first pending command by `commands.position` from each runnable group.
5. If the command declares `GPU_COUNT`, it tries to reserve GPUs that satisfy that command's `min_idle_seconds`.
6. If GPUs are insufficient, it requeues the command with `waiting_for_gpu`, skips that group for the current pass, and keeps scanning later groups.
7. If the command has no `GPU_COUNT`, it skips GPU reservation.
8. It launches selected commands in separate runner threads when their scheduling requirements are met.

This gives the desired behavior:

- same task group: serial execution;
- different task groups: parallel execution;
- failed command: blocks only its own task group.
- GPU-short command: skipped for the current pass, so later runnable groups can still use available GPUs.

Killed commands are requeued with `run_after_id` so they are selected ahead of later commands in the same group.

Commands can be added and reordered only while their task group is `draft`. This keeps
the task group as an explicit execution plan: users finish the command list, put the
first command at the top, then start the whole group.

## Launch

GPUDock launches scripts with:

```text
bash /absolute/path/to/script.sh
```

Environment assignments submitted before the script are passed into the subprocess environment. GPUDock still launches the parsed script path directly with `bash`; it does not run the submitted text through a shell.

If the submitted command includes `GPU_COUNT=<n>`, that value is used for scheduling and for the launched subprocess environment. If it is omitted, GPUDock reads the script's last `GPU_COUNT=<n>` or `export GPU_COUNT=<n>` assignment. If neither source declares `GPU_COUNT`, the task is non-GPU.

For GPU tasks, it injects:

```text
CUDA_DEVICES=<selected ids>
GPU_COUNT=<number of selected ids>
```

This overrides any submitted or parent `CUDA_DEVICES` value. `GPU_COUNT` comes from the submitted command when present, otherwise from the script.

For non-GPU tasks, GPUDock does not inject `CUDA_DEVICES` or `GPU_COUNT`.

## Email

Startup notification follows the approach in `/home/yijiali/python.py`:

- SMTP over SSL for port `465`;
- otherwise SMTP plus `starttls()`;
- MIME text message with UTF-8 body.

The notification is sent after `subprocess.Popen(...)` succeeds and the process ID has been recorded.

## Process Control

Scripts are launched in a new process session. The recorded PID is therefore also the process group ID for the script tree:

```text
subprocess.Popen(..., start_new_session=True)
```

Killing a launched task sends `SIGTERM` to that process group. If the group is still present after a short grace period, GPUDock follows up with `SIGKILL`. This targets the top-level bash process and child processes started by that script.

After a launched task is killed, GPUDock moves that command back to `pending`, preserves
its retry priority inside the task group, and pauses the whole task group. The command
will not be scheduled again until the user starts the task group.

Retrying a killed pending command or an error command clears the command's failure
metadata, keeps the task group paused, and marks it as requiring a manual restart.
GPUDock does not wake the scheduler for retry requests; the user must start the task
group manually before the command can be scheduled.

There is also a short pre-launch window where a task is already marked `running` but no subprocess PID has been recorded yet. A kill request during that window requeues the task with:

```text
exit_status = killed_before_launch
```

The task group is paused and marked as requiring a manual restart, so the command cannot
be claimed again until the user explicitly starts the group. Before launching, the worker
re-reads the command status. The final status check, subprocess launch, PID recording,
and assigned-GPU recording happen while holding the scheduler database lock. A kill
request therefore has only two outcomes: it requeues and pauses the task before launch,
or it sees a recorded process group PID and can signal the whole script tree.

## Visual Dashboard

The FastAPI service exposes a local dashboard at `/` and `/ui`.

The dashboard is intentionally thin: it calls the same HTTP endpoints as external clients instead of duplicating scheduler logic. It supports:

- creating task groups;
- viewing group summaries before command details;
- moving task groups up or down to control dashboard order and scheduler priority;
- opening a draft or completed group to submit commands;
- viewing queued/running/error commands separately from succeeded/canceled history;
- moving pending commands up or down before the group starts; active queue order is renumbered from 1 and excludes succeeded/canceled commands;
- starting a prepared group;
- pausing a running group so no later pending command is claimed;
- viewing GPU requirements, assigned GPU IDs, and submission timestamps;
- opening stdout/stderr logs;
- retrying, canceling, or killing commands;
- deleting completed or empty groups.

This keeps the browser UI replaceable while the API remains the source of truth.

## Failure Semantics

GPUDock distinguishes:

1. Self failure
   - Non-zero exit code.
   - Moves to `error`.
   - Blocks later commands in the same group.

2. Kill by signal
   - Negative process return code.
   - Moves back to `pending`.
   - Runs next inside its group.

3. Insufficient GPU availability
   - Scheduler condition, not a script failure.
   - Moves back to `pending`.
   - Requires enough GPUs to remain below 1% memory usage for the task's `min_idle_seconds`.

4. Validation failure
   - Invalid path or invalid `GPU_COUNT`.
   - Moves to `error` if discovered during worker execution.
   - API/CLI submission rejects invalid scripts before insert.

## Query Order

User-facing query surfaces return newest records first:

- `GET /groups`
- `GET /commands`
- `GET /commands?status=...`
- CLI command lists

Group-specific command views return planned execution order instead:

- `GET /groups/{id}/commands`
- `GET /commands?group_id=...`

In group views, the first command shown is the next command that should run.

Completed groups can be reopened by adding a new command. GPUDock moves the group back
to `draft`, so the newly submitted command is not scheduled until the user starts the
group again.

Task group views return explicit group order:

- `GET /groups`

The first group shown is the first group considered by the scheduler. `PATCH /groups/order`
replaces that order with all active task group IDs.
