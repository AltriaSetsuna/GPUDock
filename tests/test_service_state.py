from __future__ import annotations

import socket

from cmddock.service_state import (
    ServiceState,
    pick_available_port,
    read_service_state,
    running_service,
    write_service_state,
)


def test_service_state_round_trip(tmp_path):
    state = ServiceState(pid=1, host="127.0.0.1", port=8765, data_dir=str(tmp_path))

    write_service_state(tmp_path, state)

    assert read_service_state(tmp_path) == state
    assert state.url == "http://127.0.0.1:8765/"


def test_running_service_clears_stale_pid(tmp_path):
    write_service_state(
        tmp_path,
        ServiceState(pid=999999999, host="127.0.0.1", port=8765, data_dir=str(tmp_path)),
    )

    assert running_service(tmp_path) is None
    assert read_service_state(tmp_path) is None


def test_pick_available_port_falls_back_when_default_is_busy():
    host = "127.0.0.1"
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        busy_port = int(sock.getsockname()[1])

        selected_port = pick_available_port(host, busy_port)

    assert selected_port != busy_port
    assert selected_port > 0
