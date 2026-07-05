from __future__ import annotations

import os
import signal
import sys
import threading
import time

from cmddock.runner import classify_exit_code, run_command


def _write_script(tmp_path, body: str):
    script = tmp_path / "task.sh"
    script.write_text(body)
    return script


def test_classify_success():
    exit_status, killed = classify_exit_code(0)

    assert exit_status == "exited_zero"
    assert killed is False


def test_classify_signal_kill():
    exit_status, killed = classify_exit_code(-9)

    assert exit_status == "killed_by_signal:SIGKILL"
    assert killed is True


def test_classify_nonzero_exit():
    exit_status, killed = classify_exit_code(2)

    assert exit_status == "exited_nonzero:2"
    assert killed is False


def test_run_command_reports_pid(tmp_path):
    seen_pids = []
    script = _write_script(tmp_path, "printf hello")

    result = run_command(
        str(script),
        None,
        tmp_path / "stdout.log",
        tmp_path / "stderr.log",
        on_start=seen_pids.append,
    )

    assert result.exit_code == 0
    assert seen_pids
    assert (tmp_path / "stdout.log").read_text() == "hello"


def test_run_command_uses_process_group_for_script_children(tmp_path):
    seen_pids = []
    results = []
    child_pid_path = tmp_path / "child.pid"
    script = _write_script(
        tmp_path,
        "\n".join(
            [
                f"{sys.executable} -c 'import time; time.sleep(30)' &",
                f"echo $! > {child_pid_path}",
                "wait",
            ]
        ),
    )

    thread = threading.Thread(
        target=lambda: results.append(
            run_command(
                str(script),
                None,
                tmp_path / "stdout.log",
                tmp_path / "stderr.log",
                on_start=seen_pids.append,
            )
        )
    )
    thread.start()

    deadline = time.monotonic() + 5
    while not seen_pids or not child_pid_path.exists():
        if time.monotonic() > deadline:
            raise AssertionError("Timed out waiting for parent and child process IDs")
        time.sleep(0.01)

    parent_pid = seen_pids[0]
    child_pid = int(child_pid_path.read_text())

    deadline = time.monotonic() + 5
    while True:
        try:
            parent_process_group_id = os.getpgid(parent_pid)
            child_process_group_id = os.getpgid(child_pid)
            break
        except ProcessLookupError:
            if time.monotonic() > deadline:
                raise AssertionError("Timed out waiting for stable process group") from None
            time.sleep(0.01)

    assert parent_process_group_id == parent_pid
    assert child_process_group_id == parent_pid

    os.killpg(parent_pid, signal.SIGTERM)
    thread.join(timeout=5)

    assert not thread.is_alive()
    assert results[0].killed is True
