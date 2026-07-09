from __future__ import annotations

import json
import os
import socket
from dataclasses import asdict, dataclass
from pathlib import Path

DEFAULT_PORT = 8765
STATE_FILE_NAME = "service.json"


@dataclass(frozen=True)
class ServiceState:
    pid: int
    host: str
    port: int
    data_dir: str

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}/"


def service_state_path(data_dir: Path) -> Path:
    return data_dir / STATE_FILE_NAME


def read_service_state(data_dir: Path) -> ServiceState | None:
    path = service_state_path(data_dir)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text())
        return ServiceState(
            pid=int(payload["pid"]),
            host=str(payload["host"]),
            port=int(payload["port"]),
            data_dir=str(payload.get("data_dir", data_dir)),
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def write_service_state(data_dir: Path, state: ServiceState) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    service_state_path(data_dir).write_text(json.dumps(asdict(state), indent=2) + "\n")


def clear_service_state(data_dir: Path) -> None:
    service_state_path(data_dir).unlink(missing_ok=True)


def process_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def is_port_available(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def pick_available_port(host: str, preferred_port: int = DEFAULT_PORT) -> int:
    if is_port_available(host, preferred_port):
        return preferred_port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def running_service(data_dir: Path) -> ServiceState | None:
    state = read_service_state(data_dir)
    if state is None:
        return None
    if process_exists(state.pid):
        return state
    clear_service_state(data_dir)
    return None
