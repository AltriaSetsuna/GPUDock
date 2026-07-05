from __future__ import annotations

import os
import signal
import time


def terminate_process_group(pid: int, grace_seconds: float = 5.0) -> None:
    """Terminate a process group, then force-kill it if it survives."""
    os.killpg(pid, signal.SIGTERM)
    deadline = time.monotonic() + grace_seconds
    while time.monotonic() < deadline:
        if not process_group_exists(pid):
            return
        time.sleep(0.05)
    if process_group_exists(pid):
        os.killpg(pid, signal.SIGKILL)


def process_group_exists(pid: int) -> bool:
    try:
        os.killpg(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
