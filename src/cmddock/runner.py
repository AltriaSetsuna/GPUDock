from __future__ import annotations

import os
import signal
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RunResult:
    exit_code: int
    exit_status: str
    killed: bool
    error_message: str | None = None


def classify_exit_code(exit_code: int) -> tuple[str, bool]:
    if exit_code == 0:
        return "exited_zero", False
    if exit_code < 0:
        signal_number = -exit_code
        try:
            signal_name = signal.Signals(signal_number).name
        except ValueError:
            signal_name = f"SIG{signal_number}"
        return f"killed_by_signal:{signal_name}", True
    if 128 < exit_code < 192:
        signal_number = exit_code - 128
        try:
            signal_name = signal.Signals(signal_number).name
        except ValueError:
            signal_name = f"SIG{signal_number}"
        return f"killed_by_signal:{signal_name}", True
    return f"exited_nonzero:{exit_code}", False


def run_command(
    command: str,
    cwd: str | None,
    stdout_path: Path,
    stderr_path: Path,
    on_start: Callable[[int], None] | None = None,
    env: dict[str, str] | None = None,
    after_start: Callable[[], None] | None = None,
) -> RunResult:
    process = start_command_process(command, cwd, stdout_path, stderr_path, env=env)
    if on_start is not None:
        on_start(process.pid)
    if after_start is not None:
        after_start()
    return wait_for_process(process)


def start_command_process(
    command: str,
    cwd: str | None,
    stdout_path: Path,
    stderr_path: Path,
    env: dict[str, str] | None = None,
) -> subprocess.Popen:
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    stderr_path.parent.mkdir(parents=True, exist_ok=True)

    with stdout_path.open("ab") as stdout_file, stderr_path.open("ab") as stderr_file:
        return subprocess.Popen(
            ["bash", command],
            cwd=cwd,
            stdout=stdout_file,
            stderr=stderr_file,
            start_new_session=True,
            env=env or os.environ.copy(),
        )


def wait_for_process(process: subprocess.Popen) -> RunResult:
    exit_code = process.wait()
    exit_status, killed = classify_exit_code(exit_code)
    error_message = None if exit_code == 0 else exit_status
    return RunResult(
        exit_code=exit_code,
        exit_status=exit_status,
        killed=killed,
        error_message=error_message,
    )
