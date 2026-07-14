from __future__ import annotations

import subprocess

import pytest

from cmddock.gpu import (
    GPUReservationManager,
    GPUSchedulingError,
    GPUStatus,
    StableIdleGPUTracker,
    get_gpu_memory_status,
    parse_gpu_count,
    parse_submission_command,
    parse_submission_environment,
    release_reserved_gpus,
    reserve_idle_gpus,
    resolve_gpu_resource,
    resolve_gpu_target,
    select_idle_gpus,
    validate_script_path,
)
from cmddock.hosts import GPUHostConfig, HostConfig, parse_gpu_host_config


def test_validate_script_path_requires_absolute_sh_path(tmp_path):
    script = tmp_path / "task.sh"
    script.write_text("export GPU_COUNT=1\n")

    assert validate_script_path(str(script)) == script

    with pytest.raises(ValueError, match="absolute"):
        validate_script_path("relative.sh")

    not_script = tmp_path / "task.txt"
    not_script.write_text("export GPU_COUNT=1\n")
    with pytest.raises(ValueError, match="ending in .sh"):
        validate_script_path(str(not_script))


def test_parse_gpu_count_reads_last_assignment(tmp_path):
    script = tmp_path / "task.sh"
    script.write_text("GPU_COUNT=1\nexport GPU_COUNT=2 # override\n")

    assert parse_gpu_count(str(script)) == 2


def test_parse_gpu_count_prefers_command_env_assignment(tmp_path):
    script = tmp_path / "task.sh"
    script.write_text("export GPU_COUNT=1\n")

    assert parse_gpu_count(f"GPU_COUNT=3 bash {script}") == 3


def test_parse_gpu_count_uses_command_env_when_script_is_missing_assignment(tmp_path):
    script = tmp_path / "task.sh"
    script.write_text("echo no script GPU_COUNT\n")

    assert parse_gpu_count(f"GPU_COUNT=2 bash {script}") == 2


def test_parse_gpu_count_rejects_invalid_command_env_assignment(tmp_path):
    script = tmp_path / "task.sh"
    script.write_text("export GPU_COUNT=1\n")

    with pytest.raises(ValueError, match="Command GPU_COUNT"):
        parse_gpu_count(f"GPU_COUNT=abc bash {script}")


def test_parse_submission_command_accepts_env_prefixed_bash_script(tmp_path):
    script = tmp_path / "task.sh"
    script.write_text("export GPU_COUNT=1\n")
    command = f"DATA_PATH=/home/data.json MODEL=llama bash {script}"

    parsed = parse_submission_command(command)

    assert parsed.command == command
    assert parsed.script_path == script
    assert parsed.env_overrides == {
        "DATA_PATH": "/home/data.json",
        "MODEL": "llama",
    }
    assert parse_gpu_count(command) == 1


def test_parse_submission_command_rejects_extra_script_arguments(tmp_path):
    script = tmp_path / "task.sh"
    script.write_text("export GPU_COUNT=1\n")

    with pytest.raises(ValueError, match="absolute .sh path"):
        parse_submission_command(f"DATA_PATH=/home/data.json bash {script} --epochs 3")


def test_parse_gpu_count_treats_missing_definition_as_non_gpu_task(tmp_path):
    script = tmp_path / "task.sh"
    script.write_text("echo missing\n")

    assert parse_gpu_count(str(script)) is None


def test_parse_submission_environment_prefers_command_env_over_script(tmp_path):
    script = tmp_path / "task.sh"
    script.write_text('export VLLM_TARGET="node1_vp"\nDATA_PATH=/script.json\n')

    env = parse_submission_environment(f"DATA_PATH=/command.json bash {script}")

    assert env["VLLM_TARGET"] == "node1_vp"
    assert env["DATA_PATH"] == "/command.json"


def test_resolve_gpu_resource_uses_vllm_target_host_alias(tmp_path):
    script = tmp_path / "task.sh"
    script.write_text("export GPU_COUNT=1\n")
    config = parse_gpu_host_config(
        """
        Host node1_vp
          HostName 10.75.76.2
          User yijiali
          Port 22
          IdentityFile ~/.ssh/node1_rsa

        RemoteEnv VLLM_TARGET
        """
    )

    resource = resolve_gpu_resource(f"VLLM_TARGET=node1_vp bash {script}", config)

    assert resource == "node1_vp"


def test_resolve_gpu_resource_can_use_explicit_env_mapping(tmp_path):
    script = tmp_path / "task.sh"
    script.write_text("export VLLM_TARGET=serve-a\n")
    config = parse_gpu_host_config(
        """
        Host node1_vp
          HostName 10.75.76.2

        RemoteEnv VLLM_TARGET serve-a node1_vp
        """
    )

    assert resolve_gpu_resource(str(script), config) == "node1_vp"


def test_parse_submission_environment_reads_referenced_vllm_config(tmp_path):
    agent_dir = tmp_path / "agent"
    script_dir = agent_dir / "scripts" / "qwen"
    config_dir = agent_dir / "config"
    script_dir.mkdir(parents=True)
    config_dir.mkdir()
    script = script_dir / "fix.sh"
    script.write_text(
        'readonly VLLM_HOST_CONFIG="${VLLM_HOST_CONFIG:-${AGENT_DIR}/config/vllm_hosts.env}"\n'
        'vllm_configure_target "${VLLM_HOST_CONFIG}"\n',
    )
    (config_dir / "vllm_hosts.env").write_text(
        "VLLM_TARGET_DEFAULT=node1\n"
        "VLLM_NODE1_HOST=10.75.76.2\n"
        "VLLM_NODE1_USER=yijiali\n"
        "VLLM_NODE1_SSH_KEY=/home/yijiali/.ssh/node1_rsa\n",
    )

    env = parse_submission_environment(f"GPU_COUNT=2 bash {script}")

    assert env["VLLM_TARGET_DEFAULT"] == "node1"
    assert env["VLLM_NODE1_HOST"] == "10.75.76.2"


def test_resolve_gpu_target_uses_vllm_default_without_host_config(tmp_path):
    agent_dir = tmp_path / "agent"
    script_dir = agent_dir / "scripts" / "qwen"
    config_dir = agent_dir / "config"
    script_dir.mkdir(parents=True)
    config_dir.mkdir()
    script = script_dir / "fix.sh"
    script.write_text(
        'export GPU_COUNT=2\n'
        'readonly VLLM_HOST_CONFIG="${VLLM_HOST_CONFIG:-${AGENT_DIR}/config/vllm_hosts.env}"\n'
        'vllm_configure_target "${VLLM_HOST_CONFIG}"\n',
    )
    (config_dir / "vllm_hosts.env").write_text(
        "VLLM_TARGET_DEFAULT=node1\n"
        "VLLM_NODE1_HOST=10.75.76.2\n"
        "VLLM_NODE1_USER=yijiali\n"
        "VLLM_NODE1_SSH_KEY=/home/yijiali/.ssh/node1_rsa\n",
    )

    target = resolve_gpu_target(str(script), GPUHostConfig(hosts={}, remote_env_bindings=()))

    assert target.resource_id == "node1"
    assert target.host_config is not None
    assert target.host_config.hostname == "10.75.76.2"
    assert target.host_config.user == "yijiali"


def test_get_gpu_memory_status_queries_remote_host(tmp_path, monkeypatch):
    captured_cmd = []

    class Completed:
        stdout = "0, 0, 1000\n1, 900, 1000\n"

    def fake_run(cmd, **kwargs):
        captured_cmd.extend(cmd)
        assert kwargs["text"] is True
        assert kwargs["timeout"] == 5.0
        return Completed()

    monkeypatch.setattr("cmddock.gpu.subprocess.run", fake_run)

    statuses = get_gpu_memory_status(
        resource_id="node1_vp",
        host_config=HostConfig(
            name="node1_vp",
            hostname="10.75.76.2",
            user="yijiali",
            port=22,
            identity_file=tmp_path / "node1_rsa",
        ),
    )

    assert captured_cmd[:14] == [
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
    ]
    assert captured_cmd[-3:] == [
        "nvidia-smi",
        "--query-gpu=index,memory.used,memory.total",
        "--format=csv,noheader,nounits",
    ]
    assert [status.gpu_id for status in statuses] == [0, 1]


def test_get_gpu_memory_status_converts_timeout_to_scheduling_error(monkeypatch):
    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])

    monkeypatch.setattr("cmddock.gpu.subprocess.run", fake_run)

    with pytest.raises(GPUSchedulingError, match="timed out"):
        get_gpu_memory_status(timeout_seconds=0.25)


def test_select_idle_gpus_requires_stable_low_memory_for_120_seconds(monkeypatch):
    now = [1000.0]
    tracker = StableIdleGPUTracker(clock=lambda: now[0])
    monkeypatch.setattr(
        "cmddock.gpu.get_gpu_memory_status",
        lambda: [
            GPUStatus(gpu_id=0, memory_used_mb=0, memory_total_mb=1000),
            GPUStatus(gpu_id=1, memory_used_mb=9, memory_total_mb=1000),
            GPUStatus(gpu_id=2, memory_used_mb=10, memory_total_mb=1000),
        ],
    )

    with pytest.raises(GPUSchedulingError, match="120"):
        select_idle_gpus(1, tracker=tracker)

    now[0] += 119.9

    with pytest.raises(GPUSchedulingError, match="120"):
        select_idle_gpus(1, tracker=tracker)

    now[0] += 0.1

    selected, idle = select_idle_gpus(2, tracker=tracker)

    assert selected == [0, 1]
    assert idle == [0, 1]


def test_stable_idle_tracker_resets_when_gpu_memory_rises():
    now = [0.0]
    tracker = StableIdleGPUTracker(clock=lambda: now[0])
    low_memory = [GPUStatus(gpu_id=0, memory_used_mb=0, memory_total_mb=1000)]
    high_memory = [GPUStatus(gpu_id=0, memory_used_mb=50, memory_total_mb=1000)]

    assert tracker.get_idle_gpu_ids(low_memory) == []

    now[0] = 120.0
    assert tracker.get_idle_gpu_ids(low_memory) == [0]

    now[0] = 121.0
    assert tracker.get_idle_gpu_ids(high_memory) == []

    now[0] = 240.0
    assert tracker.get_idle_gpu_ids(low_memory) == []

    now[0] = 360.0
    assert tracker.get_idle_gpu_ids(low_memory) == [0]


def test_reservation_manager_skips_already_reserved_gpus(monkeypatch):
    now = [0.0]
    tracker = StableIdleGPUTracker(clock=lambda: now[0])
    manager = GPUReservationManager(tracker=tracker)
    monkeypatch.setattr(
        "cmddock.gpu.get_gpu_memory_status",
        lambda: [
            GPUStatus(gpu_id=0, memory_used_mb=0, memory_total_mb=1000),
            GPUStatus(gpu_id=1, memory_used_mb=0, memory_total_mb=1000),
        ],
    )

    tracker.get_idle_gpu_ids(
        [
            GPUStatus(gpu_id=0, memory_used_mb=0, memory_total_mb=1000),
            GPUStatus(gpu_id=1, memory_used_mb=0, memory_total_mb=1000),
        ]
    )
    now[0] = 120.0

    first = reserve_idle_gpus(1, manager=manager)
    second = reserve_idle_gpus(1, manager=manager)

    assert first.selected_gpu_ids == [0]
    assert second.selected_gpu_ids == [1]

    with pytest.raises(GPUSchedulingError, match="reserved"):
        reserve_idle_gpus(1, manager=manager)

    release_reserved_gpus(first.selected_gpu_ids, manager=manager)
    third = reserve_idle_gpus(1, manager=manager)

    assert third.selected_gpu_ids == [0]
