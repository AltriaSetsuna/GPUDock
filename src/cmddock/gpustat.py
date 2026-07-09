from __future__ import annotations

import subprocess
from dataclasses import dataclass

from cmddock.hosts import LOCAL_RESOURCE, GPUHostConfig, HostConfig, build_ssh_command


@dataclass(frozen=True)
class GPUStatResult:
    resource: str
    output: str
    ok: bool


def list_gpu_resources(config: GPUHostConfig) -> list[str]:
    return [LOCAL_RESOURCE, *sorted(config.hosts)]


def read_gpustat(
    resource: str,
    config: GPUHostConfig,
    timeout_seconds: float = 2.0,
) -> GPUStatResult:
    host_config = config.get_host(resource)
    cmd = build_gpustat_command(resource, host_config)
    try:
        completed = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        output = _decode_timeout_output(exc.stdout) or _decode_timeout_output(exc.stderr)
        if output:
            return GPUStatResult(resource=resource, output=_last_gpustat_frame(output), ok=True)
        return GPUStatResult(resource=resource, output="gpustat timed out.", ok=False)
    except OSError as exc:
        return GPUStatResult(resource=resource, output=str(exc), ok=False)

    output = _last_gpustat_frame(completed.stdout or completed.stderr or "")
    if not output:
        output = "gpustat returned no output."
    return GPUStatResult(resource=resource, output=output, ok=completed.returncode == 0)


def build_gpustat_command(resource: str, host_config: HostConfig | None) -> list[str]:
    cmd = ["gpustat", "-i"]
    if resource == LOCAL_RESOURCE:
        return cmd
    if host_config is None:
        raise ValueError(f"Remote GPU host '{resource}' is not configured.")
    return build_ssh_command(host_config, cmd)


def _decode_timeout_output(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return value


def _last_gpustat_frame(output: str) -> str:
    lines = [line.rstrip() for line in output.splitlines() if line.strip()]
    if not lines:
        return ""

    frame_starts = [index for index, line in enumerate(lines) if line.startswith("[0]")]
    if not frame_starts:
        return "\n".join(lines).strip()

    start = frame_starts[-1]
    if start > 0 and not lines[start - 1].startswith("["):
        start -= 1
    return "\n".join(lines[start:]).strip()
