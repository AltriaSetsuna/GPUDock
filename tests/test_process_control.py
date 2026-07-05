from __future__ import annotations

import os
import subprocess
import sys
import time

from cmddock.process_control import process_group_exists, terminate_process_group


def test_terminate_process_group_force_kills_term_ignoring_child(tmp_path):
    child_pid_path = tmp_path / "child.pid"
    script = tmp_path / "ignore-term.sh"
    script.write_text(
        "\n".join(
            [
                "#!/usr/bin/env bash",
                (
                    f"{sys.executable} -c \"import os, signal, time; "
                    "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                    f"open('{child_pid_path}', 'w').write(str(os.getpid())); "
                    "time.sleep(30)\" &"
                ),
                "wait",
            ]
        )
    )

    process = subprocess.Popen(["bash", str(script)], start_new_session=True)
    try:
        deadline = time.monotonic() + 5
        while not child_pid_path.exists():
            if time.monotonic() > deadline:
                raise AssertionError("Timed out waiting for child process")
            time.sleep(0.01)

        child_pid = int(child_pid_path.read_text())
        assert os.getpgid(child_pid) == process.pid

        terminate_process_group(process.pid, grace_seconds=0.1)
        process.wait(timeout=5)

        deadline = time.monotonic() + 5
        while process_group_exists(process.pid):
            if time.monotonic() > deadline:
                raise AssertionError("Process group survived SIGKILL fallback")
            time.sleep(0.01)
    finally:
        if process.poll() is None:
            process.kill()
