# Changelog

## 0.5.0

- Added multi-host GPU monitoring through `.cmddock/gpu_hosts.conf`.
- Added SSH-based remote `nvidia-smi` polling while keeping submitted scripts running locally.
- Added `RemoteEnv` config support so variables such as `VLLM_TARGET` can select remote GPU hosts.
- Added per-resource GPU idle tracking and reservations such as `local:0` and `node1:0`.
- Added `gpu_resource` persistence and API output for scheduled commands.
- Added fail-closed remote GPU target resolution for vLLM defaults, including `config/vllm_hosts.env` support.
- Added a local default `.cmddock/gpu_hosts.conf` for `node1` and `VLLM_TARGET`.
- Removed hardcoded email addresses and SMTP credentials from code and docs.
- Allowed `error` commands to be canceled so a blocked task group can continue or be deleted.
- Avoided transient false `running` status while a task is only checking GPU availability.
- Added `.bashrc` GPUDock email block fallback when email environment variables are absent.
- Added a fixed lower-left GPU status widget backed by local and remote `gpustat -i` snapshots.
- Added `install.sh` and `uninstall.sh` for a persistent user-level `gpudock` command.
- Added service state tracking, `gpudock status`, automatic fallback ports, and single-instance `serve` behavior.
- Prevented sourced install/uninstall scripts from leaking shell options such as `set -e` into the current terminal.
- Documented how to add additional cross-server environment selectors with `RemoteEnv`.
- Updated the GPU Status panel to match the Create Group width and ignore stale resource-switch responses.
- Added dashboard loading and compatibility notes so Task Groups does not appear empty before `/groups` returns.
- Updated the dashboard, README, design docs, and tests for remote GPU scheduling.

## 0.4.0

- Replaced user-facing `serial` / `parallel` queues with task groups.
- Added task group creation, listing, detail views, and deletion.
- Changed scheduling so each task group runs serially while different groups run in parallel.
- Added group-level blocking when a command enters `error`.
- Restricted task group deletion to groups whose commands all succeeded or were canceled.
- Updated the dashboard to show task groups first and command details inside each group.
- Kept legacy database migration support for older queue-based command rows.

## 0.3.0

- Renamed the user-facing project to GPUDock.
- Restricted submitted commands to absolute `.sh` bash script paths.
- Added `GPU_COUNT` parsing from submitted scripts.
- Added idle GPU selection using only GPUs with memory usage below 1%.
- Injected `CUDA_DEVICES` and `GPU_COUNT` into launched script environments.
- Added startup email notification based on `/home/yijiali/python.py`.
- Added a local visual dashboard for submitting, filtering, controlling, and inspecting tasks.
- Reworked the README quick start for public open-source readers.
- Changed GPU idleness from an instant sample to a 120-second stable low-memory window.
- Accepted env-prefixed bash launch commands such as `DATA_PATH=/x bash /train.sh`.
- Made submitted `GPU_COUNT=<n>` override script-level `GPU_COUNT` parsing.
- Added process-local GPU reservations to prevent parallel launches from sharing one GPU.
- Documented and tested process-group killing so script child processes are signaled.
- Allowed kill requests during the pre-launch running window before a PID is recorded.
- Added SIGKILL fallback when a killed process group survives SIGTERM.

## 0.2.0

- Added `serial` and `parallel` queue modes using a single unified `commands` table.
- Added `queue` to command creation, command records, CLI filters, and HTTP filters.
- Added a parallel dispatcher that immediately starts all pending parallel commands.
- Preserved default serial behavior for existing usage.
- Documented the single-table queue-mode design in `docs/design.md`.

## 0.1.0

- Added the initial local command queue daemon.
- Added SQLite persistence, CLI commands, HTTP API, logs, kill/requeue behavior, and tests.
