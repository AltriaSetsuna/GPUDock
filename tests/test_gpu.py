from __future__ import annotations

import pytest

from cmddock.gpu import (
    GPUSchedulingError,
    GPUStatus,
    StableIdleGPUTracker,
    parse_gpu_count,
    parse_submission_command,
    select_idle_gpus,
    validate_script_path,
)


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


def test_parse_gpu_count_requires_definition(tmp_path):
    script = tmp_path / "task.sh"
    script.write_text("echo missing\n")

    with pytest.raises(ValueError, match="GPU_COUNT"):
        parse_gpu_count(str(script))


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
