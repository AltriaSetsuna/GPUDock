from __future__ import annotations

import logging
import os
import threading
from pathlib import Path

from cmddock.database import Database
from cmddock.emailer import send_launch_email_async
from cmddock.gpu import (
    GPUSchedulingError,
    parse_gpu_count,
    parse_submission_command,
    release_reserved_gpus,
    reserve_idle_gpus,
)
from cmddock.models import CommandStatus
from cmddock.runner import start_command_process, wait_for_process

logger = logging.getLogger(__name__)


class CommandRunner:
    def __init__(self, database: Database, logs_dir: Path) -> None:
        self.database = database
        self.logs_dir = logs_dir

    def run_one(self, command: dict) -> bool:
        command_id = command["id"]
        command_text = command["command"]
        stdout_path = self.logs_dir / f"{command_id}.stdout.log"
        stderr_path = self.logs_dir / f"{command_id}.stderr.log"
        self.database.set_log_paths(command_id, stdout_path, stderr_path)

        try:
            parsed = parse_submission_command(command_text)
            script_path = str(parsed.script_path)
            gpu_count = parse_gpu_count(command_text)
            self.database.set_gpu_requirement(command_id, gpu_count)
            reservation = reserve_idle_gpus(gpu_count)
        except GPUSchedulingError as exc:
            self.database.requeue_waiting_for_gpu(command_id, str(exc))
            return False
        except Exception as exc:  # noqa: BLE001 - invalid scripts belong in the error state.
            logger.exception("Command %s failed validation before launch", command_id)
            self.database.mark_error(command_id, None, "validation_error", str(exc))
            return True

        selected_gpus = reservation.selected_gpu_ids
        try:
            current = self.database.get_command(command_id)
            if current["status"] != CommandStatus.RUNNING:
                return True

            idle_gpus = reservation.idle_gpu_ids
            cuda_devices = ",".join(str(gpu_id) for gpu_id in selected_gpus)
            env = os.environ.copy()
            env.update(parsed.env_overrides)
            env["CUDA_DEVICES"] = cuda_devices
            env["GPU_COUNT"] = str(gpu_count)
            process = self.database.start_process_if_running(
                command_id,
                cuda_devices,
                lambda: start_command_process(
                    script_path,
                    command["cwd"],
                    stdout_path,
                    stderr_path,
                    env=env,
                ),
            )
            if process is None:
                return True

            send_launch_email_async(
                script_path=script_path,
                selected_gpus=selected_gpus,
                idle_gpus=idle_gpus,
                command_id=command_id,
            )
            result = wait_for_process(process)
        except Exception as exc:  # noqa: BLE001 - runner failures belong in the error state.
            logger.exception("Command %s failed before subprocess completion", command_id)
            self.database.mark_error(command_id, None, "runner_exception", str(exc))
            return True
        finally:
            release_reserved_gpus(selected_gpus)

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


class GroupScheduler:
    def __init__(
        self,
        database: Database,
        logs_dir: Path,
        poll_interval_seconds: float = 1.0,
    ) -> None:
        self.database = database
        self.logs_dir = logs_dir
        self.poll_interval_seconds = poll_interval_seconds
        self.runner = CommandRunner(database, logs_dir)
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
            while not self._stop_event.is_set():
                command = self.database.claim_next_pending_command()
                if command is None:
                    break
                dispatched = True
                self._start_command_thread(command)
            if not dispatched:
                with self._condition:
                    self._condition.wait(timeout=self.poll_interval_seconds)

    def _start_command_thread(self, command: dict) -> None:
        thread = threading.Thread(
            target=self._run_and_forget,
            args=(command,),
            name=f"gpudock-command-{command['id']}",
            daemon=True,
        )
        with self._running_lock:
            self._running_threads.add(thread)
        thread.start()

    def _run_and_forget(self, command: dict) -> None:
        try:
            self.runner.run_one(command)
        finally:
            current_thread = threading.current_thread()
            with self._running_lock:
                self._running_threads.discard(current_thread)
