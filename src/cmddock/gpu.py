from __future__ import annotations

import re
import shlex
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from cmddock.hosts import LOCAL_RESOURCE, GPUHostConfig, HostConfig, build_ssh_command
from cmddock.scheduling import DEFAULT_MIN_IDLE_SECONDS, MAX_MIN_IDLE_SECONDS

GPU_COUNT_PATTERN = re.compile(
    r"""(?m)^\s*(?:export\s+)?GPU_COUNT\s*=\s*["']?(?P<count>\d+)["']?\s*(?:#.*)?$"""
)
ENV_ASSIGNMENT_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=.*$")
SCRIPT_ENV_ASSIGNMENT_PATTERN = re.compile(
    r"""(?m)^\s*(?:(?:export|readonly)\s+)?(?P<key>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?P<value>[^#\n]+?)\s*(?:#.*)?$"""
)
VLLM_HOST_CONFIG_ENV = "VLLM_HOST_CONFIG"
VLLM_HOST_CONFIG_NAME = "vllm_hosts.env"
VLLM_REMOTE_HINTS = ("VLLM_TARGET", "VLLM_HOST_CONFIG", "vllm_configure_target")
IDLE_MEMORY_THRESHOLD = 0.01
IDLE_STABILITY_SECONDS = float(DEFAULT_MIN_IDLE_SECONDS)
MAX_IDLE_SECONDS = float(MAX_MIN_IDLE_SECONDS)


@dataclass(frozen=True)
class ParsedCommand:
    command: str
    script_path: Path
    env_overrides: dict[str, str]


@dataclass(frozen=True)
class GPUReservation:
    selected_gpu_ids: list[int]
    idle_gpu_ids: list[int]
    resource_id: str = LOCAL_RESOURCE


@dataclass(frozen=True)
class ResolvedGPUResource:
    resource_id: str
    host_config: HostConfig | None = None


@dataclass(frozen=True)
class GPUStatus:
    gpu_id: int
    memory_used_mb: float
    memory_total_mb: float

    @property
    def memory_usage_ratio(self) -> float:
        if self.memory_total_mb <= 0:
            return 1.0
        return self.memory_used_mb / self.memory_total_mb


class GPUSchedulingError(RuntimeError):
    pass


class StableIdleGPUTracker:
    def __init__(self, clock=time.monotonic) -> None:
        self._clock = clock
        self._low_memory_since_by_gpu_key: dict[tuple[str, int], float] = {}
        self._lock = threading.Lock()

    def get_idle_gpu_ids(
        self,
        statuses: list[GPUStatus],
        resource_id: str = LOCAL_RESOURCE,
        threshold: float = IDLE_MEMORY_THRESHOLD,
        stability_seconds: float = IDLE_STABILITY_SECONDS,
        max_idle_seconds: float = MAX_IDLE_SECONDS,
    ) -> list[int]:
        now = self._clock()
        observed_gpu_keys = {(resource_id, status.gpu_id) for status in statuses}

        with self._lock:
            for gpu_key in list(self._low_memory_since_by_gpu_key):
                if gpu_key[0] == resource_id and gpu_key not in observed_gpu_keys:
                    del self._low_memory_since_by_gpu_key[gpu_key]

            idle_gpu_ids: list[int] = []
            for status in statuses:
                gpu_key = (resource_id, status.gpu_id)
                if status.memory_usage_ratio < threshold:
                    self._low_memory_since_by_gpu_key.setdefault(gpu_key, now)
                    low_memory_since = self._low_memory_since_by_gpu_key[gpu_key]
                    idle_seconds = min(max(now - low_memory_since, 0.0), max_idle_seconds)
                    if idle_seconds >= max_idle_seconds:
                        self._low_memory_since_by_gpu_key[gpu_key] = now - max_idle_seconds
                    if idle_seconds >= stability_seconds:
                        idle_gpu_ids.append(status.gpu_id)
                else:
                    self._low_memory_since_by_gpu_key.pop(gpu_key, None)
            return idle_gpu_ids


DEFAULT_IDLE_TRACKER = StableIdleGPUTracker()


class GPUReservationManager:
    def __init__(self, tracker: StableIdleGPUTracker = DEFAULT_IDLE_TRACKER) -> None:
        self._tracker = tracker
        self._reserved_gpu_keys: set[tuple[str, int]] = set()
        self._lock = threading.Lock()

    def reserve(
        self,
        gpu_count: int,
        resource_id: str = LOCAL_RESOURCE,
        host_config: HostConfig | None = None,
        threshold: float = IDLE_MEMORY_THRESHOLD,
        stability_seconds: float = IDLE_STABILITY_SECONDS,
    ) -> GPUReservation:
        statuses = (
            get_gpu_memory_status()
            if resource_id == LOCAL_RESOURCE and host_config is None
            else get_gpu_memory_status(resource_id=resource_id, host_config=host_config)
        )
        with self._lock:
            idle_gpu_ids = self._tracker.get_idle_gpu_ids(
                statuses,
                resource_id,
                threshold,
                stability_seconds,
                MAX_IDLE_SECONDS,
            )
            available_gpu_ids = [
                gpu_id
                for gpu_id in idle_gpu_ids
                if (resource_id, gpu_id) not in self._reserved_gpu_keys
            ]
            if len(available_gpu_ids) < gpu_count:
                threshold_percent = threshold * 100
                stability_display = f"{stability_seconds:g}"
                raise GPUSchedulingError(
                    f"Need {gpu_count} idle GPU(s) on {resource_id}, but only "
                    f"{len(available_gpu_ids)} GPU(s) are stable-idle and not reserved "
                    "by GPUDock. "
                    f"{len(idle_gpu_ids)} GPU(s) have stayed below "
                    f"{threshold_percent:g}% memory usage for {stability_display} "
                    "second(s)."
                )
            selected_gpu_ids = available_gpu_ids[:gpu_count]
            self._reserved_gpu_keys.update((resource_id, gpu_id) for gpu_id in selected_gpu_ids)
            return GPUReservation(selected_gpu_ids, idle_gpu_ids, resource_id)

    def release(self, gpu_ids: list[int], resource_id: str = LOCAL_RESOURCE) -> None:
        with self._lock:
            for gpu_id in gpu_ids:
                self._reserved_gpu_keys.discard((resource_id, gpu_id))

    def clear(self) -> None:
        with self._lock:
            self._reserved_gpu_keys.clear()


DEFAULT_RESERVATION_MANAGER = GPUReservationManager()


def validate_script_path(script_path: str) -> Path:
    path = Path(script_path)
    if not path.is_absolute():
        raise ValueError("Only absolute bash script paths are accepted.")
    if path.suffix != ".sh":
        raise ValueError("Only bash script paths ending in .sh are accepted.")
    if path.name.startswith("-"):
        raise ValueError("Bash script path cannot start with '-'.")
    if not path.exists():
        raise ValueError(f"Bash script does not exist: {script_path}")
    if not path.is_file():
        raise ValueError(f"Bash script path is not a file: {script_path}")
    return path


def parse_submission_command(command: str) -> ParsedCommand:
    try:
        parts = shlex.split(command)
    except ValueError as exc:
        raise ValueError(f"Invalid command syntax: {exc}") from exc

    if not parts:
        raise ValueError("Command cannot be empty.")

    env_overrides: dict[str, str] = {}
    index = 0
    while index < len(parts) and ENV_ASSIGNMENT_PATTERN.match(parts[index]):
        key, value = parts[index].split("=", 1)
        env_overrides[key] = value
        index += 1

    if index < len(parts) and parts[index] == "bash":
        index += 1

    remaining = parts[index:]
    if len(remaining) != 1:
        raise ValueError(
            "Command must be an absolute .sh path, optionally prefixed with "
            "environment assignments and bash."
        )

    return ParsedCommand(
        command=command,
        script_path=validate_script_path(remaining[0]),
        env_overrides=env_overrides,
    )


def parse_gpu_count(command: str) -> int | None:
    parsed = parse_submission_command(command)
    if "GPU_COUNT" in parsed.env_overrides:
        return _parse_positive_gpu_count(
            parsed.env_overrides["GPU_COUNT"],
            "Command GPU_COUNT",
        )

    path = parsed.script_path
    content = path.read_text(errors="replace")
    matches = list(GPU_COUNT_PATTERN.finditer(content))
    if not matches:
        return None
    return _parse_positive_gpu_count(matches[-1].group("count"), "GPU_COUNT")


def parse_submission_environment(command: str) -> dict[str, str]:
    parsed = parse_submission_command(command)
    script_env = parse_script_environment(parsed.script_path)
    referenced_env = parse_referenced_environment_files(
        parsed.script_path,
        {**script_env, **parsed.env_overrides},
    )
    return {**script_env, **referenced_env, **parsed.env_overrides}


def parse_script_environment(script_path: Path) -> dict[str, str]:
    content = script_path.read_text(errors="replace")
    env: dict[str, str] = {}
    for match in SCRIPT_ENV_ASSIGNMENT_PATTERN.finditer(content):
        key = match.group("key")
        value = _strip_shell_quotes(match.group("value").strip())
        env[key] = value
    return env


def parse_referenced_environment_files(script_path: Path, env: dict[str, str]) -> dict[str, str]:
    referenced_env: dict[str, str] = {}
    for config_path in _candidate_vllm_config_paths(script_path, env):
        if config_path.exists() and config_path.is_file():
            referenced_env.update(parse_env_assignment_file(config_path))
    return referenced_env


def parse_env_assignment_file(path: Path) -> dict[str, str]:
    content = path.read_text(errors="replace")
    env: dict[str, str] = {}
    for match in SCRIPT_ENV_ASSIGNMENT_PATTERN.finditer(content):
        env[match.group("key")] = _strip_shell_quotes(match.group("value").strip())
    return env


def resolve_gpu_resource(command: str, gpu_host_config: GPUHostConfig) -> str:
    return resolve_gpu_target(command, gpu_host_config).resource_id


def resolve_gpu_target(command: str, gpu_host_config: GPUHostConfig) -> ResolvedGPUResource:
    selection = gpu_host_config.select_resource_for_env(parse_submission_environment(command))
    return ResolvedGPUResource(selection.resource_id, selection.host_config)


def _candidate_vllm_config_paths(script_path: Path, env: dict[str, str]) -> list[Path]:
    candidates: list[Path] = []
    configured_path = env.get(VLLM_HOST_CONFIG_ENV)
    if configured_path:
        candidates.append(_resolve_env_path(configured_path, script_path.parent))

    content = script_path.read_text(errors="replace")
    if any(hint in content for hint in VLLM_REMOTE_HINTS):
        for ancestor in script_path.parents:
            candidates.append(ancestor / "config" / VLLM_HOST_CONFIG_NAME)

    unique_candidates: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.expanduser()
        if resolved not in seen:
            unique_candidates.append(resolved)
            seen.add(resolved)
    return unique_candidates


def _resolve_env_path(value: str, base_dir: Path) -> Path:
    stripped = _strip_shell_quotes(value.strip())
    if "${" in stripped or "$" in stripped:
        return base_dir / stripped
    path = Path(stripped).expanduser()
    if path.is_absolute():
        return path
    return base_dir / path


def _parse_positive_gpu_count(value: str, source: str) -> int:
    try:
        gpu_count = int(value)
    except ValueError as exc:
        raise ValueError(f"{source} must be a positive integer.") from exc
    if gpu_count <= 0:
        raise ValueError(f"{source} must be greater than 0.")
    return gpu_count


def _strip_shell_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def get_gpu_memory_status(
    resource_id: str = LOCAL_RESOURCE,
    host_config: HostConfig | None = None,
) -> list[GPUStatus]:
    cmd = [
        "nvidia-smi",
        "--query-gpu=index,memory.used,memory.total",
        "--format=csv,noheader,nounits",
    ]
    if resource_id != LOCAL_RESOURCE:
        if host_config is None:
            raise ValueError(f"Remote GPU host '{resource_id}' is not configured.")
        cmd = build_ssh_command(host_config, cmd)
    output = subprocess.check_output(cmd, text=True).strip()
    statuses: list[GPUStatus] = []
    for line in output.splitlines():
        if not line.strip():
            continue
        parts = [part.strip() for part in line.split(",")]
        if len(parts) != 3:
            continue
        statuses.append(
            GPUStatus(
                gpu_id=int(parts[0]),
                memory_used_mb=float(parts[1]),
                memory_total_mb=float(parts[2]),
            )
        )
    return statuses


def get_idle_gpu_ids(
    threshold: float = IDLE_MEMORY_THRESHOLD,
    stability_seconds: float = IDLE_STABILITY_SECONDS,
    tracker: StableIdleGPUTracker = DEFAULT_IDLE_TRACKER,
    resource_id: str = LOCAL_RESOURCE,
    host_config: HostConfig | None = None,
) -> list[int]:
    statuses = (
        get_gpu_memory_status()
        if resource_id == LOCAL_RESOURCE and host_config is None
        else get_gpu_memory_status(resource_id=resource_id, host_config=host_config)
    )
    return tracker.get_idle_gpu_ids(
        statuses,
        resource_id,
        threshold,
        stability_seconds,
        MAX_IDLE_SECONDS,
    )


def select_idle_gpus(
    gpu_count: int,
    threshold: float = IDLE_MEMORY_THRESHOLD,
    stability_seconds: float = IDLE_STABILITY_SECONDS,
    tracker: StableIdleGPUTracker = DEFAULT_IDLE_TRACKER,
    resource_id: str = LOCAL_RESOURCE,
    host_config: HostConfig | None = None,
) -> tuple[list[int], list[int]]:
    idle_gpu_ids = get_idle_gpu_ids(
        threshold,
        stability_seconds,
        tracker,
        resource_id,
        host_config,
    )
    if len(idle_gpu_ids) < gpu_count:
        threshold_percent = threshold * 100
        stability_display = f"{stability_seconds:g}"
        raise GPUSchedulingError(
            f"Need {gpu_count} idle GPU(s) on {resource_id}, but only {len(idle_gpu_ids)} "
            "GPU(s) "
            f"have stayed below {threshold_percent:g}% memory usage for "
            f"{stability_display} second(s)."
        )
    return idle_gpu_ids[:gpu_count], idle_gpu_ids


def reserve_idle_gpus(
    gpu_count: int,
    threshold: float = IDLE_MEMORY_THRESHOLD,
    stability_seconds: float = IDLE_STABILITY_SECONDS,
    manager: GPUReservationManager = DEFAULT_RESERVATION_MANAGER,
    resource_id: str = LOCAL_RESOURCE,
    host_config: HostConfig | None = None,
) -> GPUReservation:
    return manager.reserve(gpu_count, resource_id, host_config, threshold, stability_seconds)


def release_reserved_gpus(
    gpu_ids: list[int],
    manager: GPUReservationManager = DEFAULT_RESERVATION_MANAGER,
    resource_id: str = LOCAL_RESOURCE,
) -> None:
    manager.release(gpu_ids, resource_id)


def format_gpu_labels(resource_id: str, gpu_ids: list[int]) -> str:
    return ",".join(f"{resource_id}:{gpu_id}" for gpu_id in gpu_ids)
