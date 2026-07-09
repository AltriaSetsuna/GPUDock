from __future__ import annotations

import time

from cmddock.database import Database
from cmddock.gpu import GPUReservation, GPUSchedulingError
from cmddock.hosts import GPUHostConfig, HostConfig, RemoteEnvBinding
from cmddock.models import CommandStatus
from cmddock.worker import CommandRunner, GroupScheduler


def _wait_for_statuses(
    database: Database,
    expected: dict[int, CommandStatus],
    timeout_seconds: float = 5.0,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        records = {record["id"]: record for record in database.list_commands()}
        if all(records[command_id]["status"] == status for command_id, status in expected.items()):
            return
        time.sleep(0.05)
    records = {record["id"]: record for record in database.list_commands()}
    observed = {command_id: records[command_id]["status"] for command_id in expected}
    raise AssertionError(f"Timed out waiting for statuses. Observed: {observed}")


def _write_script(tmp_path, name: str, body: str):
    script = tmp_path / name
    script.write_text(f"export GPU_COUNT=1\n{body}")
    return script


def test_group_scheduler_runs_one_command_per_group_at_a_time(tmp_path, monkeypatch):
    database = Database(tmp_path / "cmddock.db")
    logs_dir = tmp_path / "logs"
    monkeypatch.setattr(
        "cmddock.worker.reserve_idle_gpus",
        lambda gpu_count, **kwargs: GPUReservation([0], [0, 1, 2]),
    )
    monkeypatch.setattr("cmddock.worker.release_reserved_gpus", lambda gpu_ids: None)
    monkeypatch.setattr("cmddock.worker.send_launch_email_async", lambda **kwargs: None)

    group_one = database.create_task_group("group-one")
    group_two = database.create_task_group("group-two")
    one_first_script = _write_script(tmp_path, "one-first.sh", "printf one-first")
    one_second_script = _write_script(tmp_path, "one-second.sh", "printf one-second")
    two_first_script = _write_script(tmp_path, "two-first.sh", "printf two-first")

    one_first = database.create_command(str(one_first_script), None, group_id=group_one["id"])
    one_second = database.create_command(str(one_second_script), None, group_id=group_one["id"])
    two_first = database.create_command(str(two_first_script), None, group_id=group_two["id"])
    database.start_task_group(group_one["id"])
    database.start_task_group(group_two["id"])

    scheduler = GroupScheduler(database, logs_dir, poll_interval_seconds=0.05)
    scheduler.start()
    try:
        _wait_for_statuses(
            database,
            {
                one_first["id"]: CommandStatus.SUCCEEDED,
                one_second["id"]: CommandStatus.SUCCEEDED,
                two_first["id"]: CommandStatus.SUCCEEDED,
            },
        )
    finally:
        scheduler.stop()

    group_one_records = database.list_commands(group_id=group_one["id"])
    group_two_records = database.list_commands(group_id=group_two["id"])

    assert [record["id"] for record in group_one_records] == [one_first["id"], one_second["id"]]
    assert [record["id"] for record in group_two_records] == [two_first["id"]]
    assert (logs_dir / f"{one_first['id']}.stdout.log").read_text() == "one-first"
    assert (logs_dir / f"{one_second['id']}.stdout.log").read_text() == "one-second"
    assert (logs_dir / f"{two_first['id']}.stdout.log").read_text() == "two-first"


def test_group_scheduler_skips_gpu_blocked_group_and_runs_later_group(tmp_path, monkeypatch):
    database = Database(tmp_path / "cmddock.db")
    logs_dir = tmp_path / "logs"
    monkeypatch.setattr("cmddock.worker.release_reserved_gpus", lambda gpu_ids: None)
    monkeypatch.setattr("cmddock.worker.send_launch_email_async", lambda **kwargs: None)

    group_a = database.create_task_group("group-a")
    group_b = database.create_task_group("group-b")
    group_c = database.create_task_group("group-c")
    a_script = _write_script(tmp_path, "a.sh", "sleep 0.2")
    b_script = _write_script(tmp_path, "b.sh", "export GPU_COUNT=2\nprintf b")
    c_script = _write_script(tmp_path, "c.sh", "printf c")
    a_task = database.create_command(str(a_script), None, group_id=group_a["id"])
    b_task = database.create_command(str(b_script), None, group_id=group_b["id"])
    c_task = database.create_command(str(c_script), None, group_id=group_c["id"])
    database.start_task_group(group_a["id"])
    database.start_task_group(group_b["id"])
    database.start_task_group(group_c["id"])

    def reserve_by_size(gpu_count, **kwargs):
        if gpu_count > 1:
            raise GPUSchedulingError("only one GPU is available")
        return GPUReservation([0], [0])

    monkeypatch.setattr("cmddock.worker.reserve_idle_gpus", reserve_by_size)

    scheduler = GroupScheduler(database, logs_dir, poll_interval_seconds=0.05)
    scheduler.start()
    try:
        _wait_for_statuses(
            database,
            {
                a_task["id"]: CommandStatus.SUCCEEDED,
                c_task["id"]: CommandStatus.SUCCEEDED,
            },
        )
    finally:
        scheduler.stop()

    b_record = database.get_command(b_task["id"])

    assert b_record["status"] == CommandStatus.PENDING
    assert b_record["exit_status"] == "waiting_for_gpu"
    assert (logs_dir / f"{c_task['id']}.stdout.log").read_text() == "c"


def test_command_runner_passes_submission_env_overrides(tmp_path, monkeypatch):
    database = Database(tmp_path / "cmddock.db")
    logs_dir = tmp_path / "logs"
    monkeypatch.setattr(
        "cmddock.worker.reserve_idle_gpus",
        lambda gpu_count, **kwargs: GPUReservation([3], [3, 4]),
    )
    monkeypatch.setattr("cmddock.worker.release_reserved_gpus", lambda gpu_ids: None)
    monkeypatch.setattr("cmddock.worker.send_launch_email_async", lambda **kwargs: None)

    script = _write_script(
        tmp_path,
        "env.sh",
        'printf "%s|%s|%s" "$DATA_PATH" "$CUDA_DEVICES" "$GPU_COUNT"',
    )
    command = f"DATA_PATH=/home/data.json bash {script}"
    record = database.create_command(command, None)
    database.start_task_group(record["group_id"])
    claimed = database.claim_next_pending_command()

    launched = CommandRunner(database, logs_dir).run_one(claimed)

    assert launched is True
    assert database.get_command(record["id"])["status"] == CommandStatus.SUCCEEDED
    assert (logs_dir / f"{record['id']}.stdout.log").read_text() == "/home/data.json|3|1"


def test_command_runner_reserves_remote_gpu_but_runs_script_locally(tmp_path, monkeypatch):
    database = Database(tmp_path / "cmddock.db")
    logs_dir = tmp_path / "logs"
    reserve_calls = []
    release_calls = []
    launched_envs = []

    def reserve_remote(gpu_count, **kwargs):
        reserve_calls.append((gpu_count, kwargs))
        return GPUReservation([1, 2], [1, 2, 3], "node1_vp")

    class Process:
        pid = 12345

    def launch_local(script_path, cwd, stdout_path, stderr_path, env):
        launched_envs.append(env.copy())
        stdout_path.parent.mkdir(parents=True, exist_ok=True)
        stdout_path.write_text("launched")
        return Process()

    monkeypatch.setattr("cmddock.worker.reserve_idle_gpus", reserve_remote)
    def release_remote(gpu_ids, **kwargs):
        release_calls.append((gpu_ids, kwargs))

    class Result:
        exit_code = 0
        killed = False

    monkeypatch.setattr("cmddock.worker.release_reserved_gpus", release_remote)
    monkeypatch.setattr("cmddock.worker.start_command_process", launch_local)
    monkeypatch.setattr("cmddock.worker.wait_for_process", lambda process: Result())
    monkeypatch.setattr("cmddock.worker.send_launch_email_async", lambda **kwargs: None)

    script = _write_script(tmp_path, "remote.sh", 'printf "%s" "$CUDA_DEVICES"')
    record = database.create_command(f"VLLM_TARGET=node1_vp GPU_COUNT=2 bash {script}", None)
    database.start_task_group(record["group_id"])
    claimed = database.claim_next_pending_command()
    gpu_host_config = GPUHostConfig(
        hosts={"node1_vp": HostConfig(name="node1_vp", hostname="10.75.76.2")},
        remote_env_bindings=(RemoteEnvBinding(env_name="VLLM_TARGET"),),
    )

    launched = CommandRunner(database, logs_dir, gpu_host_config).run_one(claimed)
    command_record = database.get_command(record["id"])

    assert launched is True
    assert reserve_calls[0][0] == 2
    assert reserve_calls[0][1]["resource_id"] == "node1_vp"
    assert reserve_calls[0][1]["host_config"].hostname == "10.75.76.2"
    assert launched_envs[0]["CUDA_DEVICES"] == "1,2"
    assert launched_envs[0]["GPU_COUNT"] == "2"
    assert launched_envs[0]["VLLM_TARGET"] == "node1_vp"
    assert command_record["status"] == CommandStatus.SUCCEEDED
    assert command_record["gpu_resource"] == "node1_vp"
    assert command_record["assigned_gpu_ids"] is None
    assert release_calls == [([1, 2], {"resource_id": "node1_vp"})]


def test_command_runner_uses_vllm_config_default_for_remote_gpu(tmp_path, monkeypatch):
    database = Database(tmp_path / "cmddock.db")
    logs_dir = tmp_path / "logs"
    reserve_calls = []

    def reserve_remote(gpu_count, **kwargs):
        reserve_calls.append((gpu_count, kwargs))
        return GPUReservation([6, 7], [6, 7], "node1")

    class Process:
        pid = 12345

    class Result:
        exit_code = 0
        killed = False

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

    monkeypatch.setattr("cmddock.worker.reserve_idle_gpus", reserve_remote)
    monkeypatch.setattr("cmddock.worker.release_reserved_gpus", lambda gpu_ids, **kwargs: None)
    monkeypatch.setattr("cmddock.worker.start_command_process", lambda *args, **kwargs: Process())
    monkeypatch.setattr("cmddock.worker.wait_for_process", lambda process: Result())
    monkeypatch.setattr("cmddock.worker.send_launch_email_async", lambda **kwargs: None)

    record = database.create_command(str(script), None)
    database.start_task_group(record["group_id"])
    claimed = database.claim_next_pending_command()

    launched = CommandRunner(database, logs_dir).run_one(claimed)
    command_record = database.get_command(record["id"])

    assert launched is True
    assert reserve_calls[0][0] == 2
    assert reserve_calls[0][1]["resource_id"] == "node1"
    assert reserve_calls[0][1]["host_config"].hostname == "10.75.76.2"
    assert command_record["gpu_resource"] == "node1"
    assert command_record["status"] == CommandStatus.SUCCEEDED


def test_command_runner_runs_non_gpu_script_without_reservation(tmp_path, monkeypatch):
    database = Database(tmp_path / "cmddock.db")
    logs_dir = tmp_path / "logs"
    monkeypatch.delenv("GPU_COUNT", raising=False)
    monkeypatch.delenv("CUDA_DEVICES", raising=False)
    monkeypatch.setattr(
        "cmddock.worker.reserve_idle_gpus",
        lambda gpu_count, **kwargs: (_ for _ in ()).throw(
            AssertionError("non-GPU commands must not reserve GPUs"),
        ),
    )
    monkeypatch.setattr("cmddock.worker.release_reserved_gpus", lambda gpu_ids: None)
    monkeypatch.setattr("cmddock.worker.send_launch_email_async", lambda **kwargs: None)

    script = tmp_path / "no-gpu.sh"
    script.write_text(
        'printf "%s|%s" "${GPU_COUNT-unset}" "${CUDA_DEVICES-unset}"',
    )
    command = f"DATA_PATH=/home/data.json bash {script}"
    record = database.create_command(command, None)
    database.start_task_group(record["group_id"])
    claimed = database.claim_next_pending_command()

    launched = CommandRunner(database, logs_dir).run_one(claimed)
    command_record = database.get_command(record["id"])

    assert launched is True
    assert command_record["status"] == CommandStatus.SUCCEEDED
    assert command_record["gpu_count"] is None
    assert command_record["assigned_gpu_ids"] is None
    assert (logs_dir / f"{record['id']}.stdout.log").read_text() == "unset|unset"


def test_command_runner_uses_command_min_idle_seconds(tmp_path, monkeypatch):
    database = Database(tmp_path / "cmddock.db")
    logs_dir = tmp_path / "logs"
    captured_stability_seconds = []

    def reserve_with_capture(gpu_count, **kwargs):
        captured_stability_seconds.append(kwargs["stability_seconds"])
        return GPUReservation([2], [2])

    monkeypatch.setattr("cmddock.worker.reserve_idle_gpus", reserve_with_capture)
    monkeypatch.setattr("cmddock.worker.release_reserved_gpus", lambda gpu_ids: None)
    monkeypatch.setattr("cmddock.worker.send_launch_email_async", lambda **kwargs: None)

    script = _write_script(tmp_path, "custom-idle.sh", "printf idle")
    record = database.create_command(str(script), None, min_idle_seconds=300)
    database.start_task_group(record["group_id"])
    claimed = database.claim_next_pending_command()

    launched = CommandRunner(database, logs_dir).run_one(claimed)

    assert launched is True
    assert captured_stability_seconds == [300]
    assert database.get_command(record["id"])["status"] == CommandStatus.SUCCEEDED


def test_command_runner_does_not_launch_after_prelaunch_cancel(tmp_path, monkeypatch):
    database = Database(tmp_path / "cmddock.db")
    logs_dir = tmp_path / "logs"
    released_gpu_ids = []

    script = _write_script(tmp_path, "cancel-before-launch.sh", "printf should-not-run")
    record = database.create_command(str(script), None)
    database.start_task_group(record["group_id"])
    claimed = database.claim_next_pending_command()

    def reserve_then_cancel(gpu_count, **kwargs):
        database.requeue_unlaunched_killed(record["id"])
        return GPUReservation([0], [0])

    def fail_if_launched(*args, **kwargs):
        raise AssertionError("start_command_process should not be called after prelaunch cancel")

    monkeypatch.setattr("cmddock.worker.reserve_idle_gpus", reserve_then_cancel)
    monkeypatch.setattr("cmddock.worker.release_reserved_gpus", released_gpu_ids.extend)
    monkeypatch.setattr("cmddock.worker.start_command_process", fail_if_launched)

    launched = CommandRunner(database, logs_dir).run_one(claimed)

    assert launched is True
    current = database.get_command(record["id"])
    group = database.get_task_group(record["group_id"])
    assert current["status"] == CommandStatus.PENDING
    assert current["exit_status"] == "killed_before_launch"
    assert group["execution_state"] == "paused"
    assert group["manual_start_required"] is True
    assert released_gpu_ids == [0]
