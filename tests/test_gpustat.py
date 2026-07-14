from __future__ import annotations

import subprocess

from cmddock.gpustat import build_gpustat_command, list_gpu_resources, read_gpustat
from cmddock.hosts import GPUHostConfig, HostConfig, RemoteEnvBinding


def test_list_gpu_resources_includes_local_first() -> None:
    config = GPUHostConfig(
        hosts={"node1": HostConfig(name="node1", hostname="10.75.76.2")},
        remote_env_bindings=(RemoteEnvBinding(env_name="VLLM_TARGET"),),
    )

    assert list_gpu_resources(config) == ["local", "node1"]


def test_build_gpustat_command_for_remote_host(tmp_path) -> None:
    host = HostConfig(
        name="node1",
        hostname="10.75.76.2",
        user="yijiali",
        port=22,
        identity_file=tmp_path / "node1_rsa",
    )

    assert build_gpustat_command("node1", host) == [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=5",
        "-o",
        "ServerAliveInterval=5",
        "-o",
        "ServerAliveCountMax=1",
        "-p",
        "22",
        "-i",
        str(tmp_path / "node1_rsa"),
        "yijiali@10.75.76.2",
        "gpustat",
        "-i",
    ]


def test_read_gpustat_uses_timeout_output(monkeypatch) -> None:
    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], timeout=2, output="node gpu output\n")

    monkeypatch.setattr("cmddock.gpustat.subprocess.run", fake_run)

    result = read_gpustat("local", GPUHostConfig(hosts={}, remote_env_bindings=()))

    assert result.ok is True
    assert result.output == "node gpu output"


def test_read_gpustat_keeps_only_last_interval_frame(monkeypatch) -> None:
    output = """node-2 Thu Jul 9 08:42:41 2026
[0] GPU 0 | 1 / 81920 MB
[1] GPU 1 | 1 / 81920 MB
node-2 Thu Jul 9 08:42:42 2026
[0] GPU 0 | 2 / 81920 MB
[1] GPU 1 | 2 / 81920 MB
"""

    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], timeout=2, output=output)

    monkeypatch.setattr("cmddock.gpustat.subprocess.run", fake_run)

    result = read_gpustat("local", GPUHostConfig(hosts={}, remote_env_bindings=()))

    assert result.ok is True
    assert result.output == (
        "node-2 Thu Jul 9 08:42:42 2026\n"
        "[0] GPU 0 | 2 / 81920 MB\n"
        "[1] GPU 1 | 2 / 81920 MB"
    )
