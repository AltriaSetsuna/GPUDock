from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass, replace
from pathlib import Path

from cmddock.database import Database
from cmddock.emailer import send_launch_email_async
from cmddock.gpu import (
    GPUReservation,
    GPUSchedulingError,
    format_gpu_labels,
    parse_gpu_count,
    parse_submission_command,
    release_reserved_gpus,
    reserve_idle_gpus,
    resolve_gpu_target,
)
from cmddock.hosts import LOCAL_RESOURCE, GPUHostConfig
from cmddock.models import CommandStatus
from cmddock.runner import start_command_process, wait_for_process
from cmddock.scheduling import normalize_min_idle_seconds

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PreparedCommand:
    command: dict
    script_path: str
    stdout_path: Path
    stderr_path: Path
    env: dict[str, str]
    reservation: GPUReservation | None


class CommandRunner:
    def __init__(
        self,
        database: Database,
        logs_dir: Path,
        gpu_host_config: GPUHostConfig | None = None,
    ) -> None:
        self.database = database
        self.logs_dir = logs_dir
        self.gpu_host_config = gpu_host_config or GPUHostConfig(hosts={}, remote_env_bindings=())

    def run_one(self, command: dict) -> bool:
        prepared = self.prepare(command)
        if prepared is None:
            return False
        return self.run_prepared(prepared)

    def prepare(self, command: dict) -> PreparedCommand | None:
        command_id = command["id"]
        command_text = command["command"]
        stdout_path = self.logs_dir / f"{command_id}.stdout.log"
        stderr_path = self.logs_dir / f"{command_id}.stderr.log"
        self.database.set_log_paths(command_id, stdout_path, stderr_path)

        try:
            parsed = parse_submission_command(command_text)
            script_path = str(parsed.script_path)
            gpu_count = parse_gpu_count(command_text)
            gpu_target = resolve_gpu_target(command_text, self.gpu_host_config)
            gpu_resource = gpu_target.resource_id
            self.database.set_gpu_requirement(command_id, gpu_count, gpu_resource)
            min_idle_seconds = normalize_min_idle_seconds(command.get("min_idle_seconds"))
            reservation = (
                reserve_idle_gpus(
                    gpu_count,
                    stability_seconds=min_idle_seconds,
                    resource_id=gpu_resource,
                    host_config=gpu_target.host_config,
                )
                if gpu_count is not None
                else None
            )
        except GPUSchedulingError as exc:
            self.database.requeue_waiting_for_gpu(command_id, str(exc))
            return None
        except Exception as exc:  # noqa: BLE001 - invalid scripts belong in the error state.
            logger.exception("Command %s failed validation before launch", command_id)
            self.database.mark_error(command_id, None, "validation_error", str(exc))
            return None

        env = os.environ.copy()
        env.update(parsed.env_overrides)
        if reservation is not None and gpu_count is not None:
            selected_gpus = reservation.selected_gpu_ids
            cuda_devices = ",".join(str(gpu_id) for gpu_id in selected_gpus)
            env["CUDA_DEVICES"] = cuda_devices
            env["GPU_COUNT"] = str(gpu_count)
        return PreparedCommand(
            command=command,
            script_path=script_path,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            env=env,
            reservation=reservation,
        )

    def run_prepared(self, prepared: PreparedCommand) -> bool:
        command = prepared.command
        command_id = command["id"]
        reservation = prepared.reservation
        selected_gpus = reservation.selected_gpu_ids if reservation is not None else []
        try:
            current = self.database.get_command(command_id)
            if current["status"] != CommandStatus.RUNNING:
                return True

            idle_gpus = reservation.idle_gpu_ids if reservation is not None else []
            assigned_gpu_ids = (
                format_gpu_labels(reservation.resource_id, selected_gpus)
                if reservation is not None
                else None
            )
            process = self.database.start_process_if_running(
                command_id,
                assigned_gpu_ids,
                lambda: start_command_process(
                    prepared.script_path,
                    command["cwd"],
                    prepared.stdout_path,
                    prepared.stderr_path,
                    env=prepared.env,
                ),
            )
            if process is None:
                return True

            send_launch_email_async(
                script_path=prepared.script_path,
                selected_gpus=selected_gpus,
                idle_gpus=idle_gpus,
                command_id=command_id,
                gpu_resource=reservation.resource_id if reservation is not None else LOCAL_RESOURCE,
            )
            result = wait_for_process(process)
        except Exception as exc:  # noqa: BLE001 - runner failures belong in the error state.
            logger.exception("Command %s failed before subprocess completion", command_id)
            self.database.mark_error(command_id, None, "runner_exception", str(exc))
            return True
        finally:
            if selected_gpus:
                resource_id = reservation.resource_id if reservation is not None else LOCAL_RESOURCE
                if resource_id == LOCAL_RESOURCE:
                    release_reserved_gpus(selected_gpus)
                else:
                    release_reserved_gpus(selected_gpus, resource_id=resource_id)

        if result.exit_code == 0:
            self.database.mark_succeeded(command_id, result.exit_code)
        elif result.killed:
            self.database.requeue_killed(command_id, result.exit_code, result.exit_status)
        else:
            self.database.mark_error(
                command_id,
                result.exit_code,
                result.exit_status,
                result.error_message,
            )
        return True

    def release_prepared_reservation(self, prepared: PreparedCommand) -> None:
        _release_reservation(prepared.reservation)


class GroupScheduler:
    def __init__(
        self,
        database: Database,
        logs_dir: Path,
        poll_interval_seconds: float = 1.0,
        gpu_host_config: GPUHostConfig | None = None,
    ) -> None:
        self.database = database
        self.logs_dir = logs_dir
        self.poll_interval_seconds = poll_interval_seconds
        self.runner = CommandRunner(database, logs_dir, gpu_host_config)
        self._condition = threading.Condition()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._running_threads: set[threading.Thread] = set()
        self._running_lock = threading.Lock()

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        recovered = self.database.recover_interrupted_running_commands()
        if recovered:
            logger.warning("Requeued %s interrupted running command(s)", recovered)
        self._thread = threading.Thread(
            target=self.run_forever,
            name="gpudock-group-scheduler",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self.wake()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def wake(self) -> None:
        with self._condition:
            self._condition.notify_all()

    def run_forever(self) -> None:
        while not self._stop_event.is_set():
            dispatched = False
            skipped_group_ids: set[int] = set()
            while not self._stop_event.is_set():
                command = self.database.select_next_pending_command(
                    excluded_group_ids=skipped_group_ids,
                )
                if command is None:
                    break
                prepared = self.runner.prepare(command)
                if prepared is None:
                    skipped_group_ids.add(command["group_id"])
                    continue
                claimed = self.database.mark_command_running(command["id"])
                if claimed is None:
                    self.runner.release_prepared_reservation(prepared)
                    skipped_group_ids.add(command["group_id"])
                    continue
                prepared = replace(prepared, command=claimed)
                dispatched = True
                self._start_command_thread(prepared)
            if not dispatched:
                with self._condition:
                    self._condition.wait(timeout=self.poll_interval_seconds)

    def _start_command_thread(self, prepared: PreparedCommand) -> None:
        thread = threading.Thread(
            target=self._run_and_forget,
            args=(prepared,),
            name=f"gpudock-command-{prepared.command['id']}",
            daemon=True,
        )
        with self._running_lock:
            self._running_threads.add(thread)
        thread.start()

    def _run_and_forget(self, prepared: PreparedCommand) -> None:
        try:
            self.runner.run_prepared(prepared)
        finally:
            current_thread = threading.current_thread()
            with self._running_lock:
                self._running_threads.discard(current_thread)
            self.wake()


def _release_reservation(reservation: GPUReservation | None) -> None:
    if reservation is None:
        return
    if reservation.resource_id == LOCAL_RESOURCE:
        release_reserved_gpus(reservation.selected_gpu_ids)
    else:
        release_reserved_gpus(reservation.selected_gpu_ids, resource_id=reservation.resource_id)
