from __future__ import annotations

import logging
import threading
from pathlib import Path

from cmddock.database import Database
from cmddock.models import QueueMode
from cmddock.runner import run_command

logger = logging.getLogger(__name__)


class CommandRunner:
    def __init__(self, database: Database, logs_dir: Path) -> None:
        self.database = database
        self.logs_dir = logs_dir

    def run_one(self, command: dict) -> None:
        command_id = command["id"]
        stdout_path = self.logs_dir / f"{command_id}.stdout.log"
        stderr_path = self.logs_dir / f"{command_id}.stderr.log"
        self.database.set_log_paths(command_id, stdout_path, stderr_path)

        try:
            result = run_command(
                command["command"],
                command["cwd"],
                stdout_path,
                stderr_path,
                on_start=lambda pid: self.database.set_running_pid(command_id, pid),
            )
        except Exception as exc:  # noqa: BLE001 - unexpected runner failure belongs in error queue.
            logger.exception("Command %s failed before subprocess completion", command_id)
            self.database.mark_error(command_id, None, "runner_exception", str(exc))
            return

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


class CommandWorker:
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

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        recovered = self.database.recover_interrupted_running_commands(QueueMode.SERIAL)
        if recovered:
            logger.warning("Requeued %s interrupted running command(s)", recovered)
        self._thread = threading.Thread(target=self.run_forever, name="cmddock-worker", daemon=True)
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
            command = self.database.claim_next_pending_command(QueueMode.SERIAL)
            if command is None:
                with self._condition:
                    self._condition.wait(timeout=self.poll_interval_seconds)
                continue
            self.runner.run_one(command)


class ParallelDispatcher:
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
        recovered = self.database.recover_interrupted_running_commands(QueueMode.PARALLEL)
        if recovered:
            logger.warning("Requeued %s interrupted parallel command(s)", recovered)
        self._thread = threading.Thread(
            target=self.run_forever,
            name="cmddock-parallel-dispatcher",
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
                command = self.database.claim_next_pending_command(QueueMode.PARALLEL)
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
            name=f"cmddock-parallel-{command['id']}",
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
            self.wake()
