# GPUDock Design

GPUDock is a local scheduler for GPU-backed bash scripts. It keeps the simple queue mechanics from CmdDock, but constrains execution to validated script files and GPU availability.

## Goals

- Accept only absolute `.sh` script paths, optionally prefixed with environment assignments.
- Parse `GPU_COUNT` from each script.
- Launch tasks only on GPUs that stay below 1% memory usage for 120 seconds.
- Inject `CUDA_DEVICES` and override `GPU_COUNT` at launch time.
- Preserve serial and parallel queue modes.
- Requeue tasks that cannot currently acquire enough idle GPUs.
- Send a startup email after the subprocess starts.
- Provide a local visual dashboard for submitting and supervising tasks.

## Data Model

GPUDock keeps one `commands` table. The `queue` field controls scheduling strategy:

- `serial` tasks are claimed by the serial worker.
- `parallel` tasks are claimed by the parallel dispatcher.

GPU-specific fields:

- `gpu_count`: parsed from the script's `GPU_COUNT` assignment.
- `assigned_gpu_ids`: comma-separated GPU IDs injected as `CUDA_DEVICES`.

Keeping one table makes history, logs, retries, kills, and errors uniform across scheduling modes.

## Script Validation

Submissions are rejected unless `command` is:

- an absolute `.sh` file path; or
- optional `KEY=value` assignments followed by optional `bash` and an absolute `.sh` file path; and
- a script containing `GPU_COUNT=<positive integer>` or `export GPU_COUNT=<positive integer>`.

This intentionally rejects arbitrary shell strings.

Accepted examples:

```bash
/absolute/path/to/train.sh
DATA_PATH=/home/data.json bash /absolute/path/to/train.sh
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

A GPU is idle only after it has stayed below the threshold for 120 continuous seconds:

```text
memory.used / memory.total < 0.01
```

GPUDock tracks the first observed low-memory timestamp for each GPU. If a GPU rises
back to 1% memory usage or higher, its timer is reset. This avoids assigning a card
that briefly appears free while another process is still starting, shutting down, or
between allocation phases.

If a task needs `GPU_COUNT=n`, GPUDock selects the first `n` stable-idle GPU IDs. If fewer than `n` GPUs are idle, the task returns to `pending` with:

```text
exit_status = waiting_for_gpu
```

## Launch

GPUDock launches scripts with:

```text
bash /absolute/path/to/script.sh
```

Environment assignments submitted before the script are passed into the subprocess
environment. GPUDock still launches the parsed script path directly with `bash`;
it does not run the submitted text through a shell.

It injects:

```text
CUDA_DEVICES=<selected ids>
GPU_COUNT=<number of selected ids>
```

This overrides any submitted or parent `CUDA_DEVICES` and `GPU_COUNT` value. The
script's own `GPU_COUNT` assignment is still the source of the requested GPU count.

## Email

Startup notification follows the approach in `/home/yijiali/python.py`:

- SMTP over SSL for port `465`;
- otherwise SMTP plus `starttls()`;
- MIME text message with UTF-8 body.

The notification is sent after `subprocess.Popen(...)` succeeds and the process ID has been recorded.

## Queue Modes

### Serial Worker

The serial worker claims one pending `serial` task at a time. If there are not enough idle GPUs, the task is returned to `pending` and the worker waits before retrying.

### Parallel Dispatcher

The parallel dispatcher claims pending `parallel` tasks and starts a runner thread for each task. Each runner independently checks GPU availability immediately before launch. If insufficient GPUs are available, that task is returned to `pending`.

## Visual Dashboard

The FastAPI service exposes a local dashboard at `/` and `/ui`.

The dashboard is intentionally thin: it calls the same HTTP endpoints as external clients instead of duplicating scheduler logic. It supports:

- submitting absolute `.sh` script paths or env-prefixed bash launch commands;
- selecting `serial` or `parallel` queue mode;
- filtering tasks by queue and status;
- viewing GPU requirements, assigned GPU IDs, and submission timestamps;
- opening stdout/stderr logs;
- retrying, canceling, or killing tasks through the existing control endpoints.

This keeps the browser UI replaceable while the API remains the source of truth.

## Failure Semantics

GPUDock distinguishes:

1. Self failure
   - Non-zero exit code.
   - Moves to `error`.

2. Kill by signal
   - Negative process return code.
   - Moves back to `pending`.

3. Insufficient GPU availability
   - Scheduler condition, not a script failure.
   - Moves back to `pending`.
   - Requires enough GPUs to remain below 1% memory usage for 120 seconds.

4. Validation failure
   - Invalid path or missing `GPU_COUNT`.
   - Moves to `error` if discovered during worker execution.
   - API/CLI submission rejects invalid scripts before insert.

## Query Order

All query surfaces return newest records first:

- `GET /commands`
- `GET /queue`
- `GET /commands?status=...`
- `GET /commands?queue=...`
- CLI command lists
