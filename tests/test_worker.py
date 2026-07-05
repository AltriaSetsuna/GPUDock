from __future__ import annotations

import time

from cmddock.database import Database
from cmddock.gpu import GPUReservation
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
        lambda gpu_count: GPUReservation([0], [0, 1, 2]),
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


def test_command_runner_passes_submission_env_overrides(tmp_path, monkeypatch):
    database = Database(tmp_path / "cmddock.db")
    logs_dir = tmp_path / "logs"
    monkeypatch.setattr(
        "cmddock.worker.reserve_idle_gpus",
        lambda gpu_count: GPUReservation([3], [3, 4]),
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


def test_command_runner_does_not_launch_after_prelaunch_cancel(tmp_path, monkeypatch):
    database = Database(tmp_path / "cmddock.db")
    logs_dir = tmp_path / "logs"
    released_gpu_ids = []

    script = _write_script(tmp_path, "cancel-before-launch.sh", "printf should-not-run")
    record = database.create_command(str(script), None)
    database.start_task_group(record["group_id"])
    claimed = database.claim_next_pending_command()

    def reserve_then_cancel(gpu_count):
        database.cancel_unlaunched_running_command(record["id"])
        return GPUReservation([0], [0])

    def fail_if_launched(*args, **kwargs):
        raise AssertionError("start_command_process should not be called after prelaunch cancel")

    monkeypatch.setattr("cmddock.worker.reserve_idle_gpus", reserve_then_cancel)
    monkeypatch.setattr("cmddock.worker.release_reserved_gpus", released_gpu_ids.extend)
    monkeypatch.setattr("cmddock.worker.start_command_process", fail_if_launched)

    launched = CommandRunner(database, logs_dir).run_one(claimed)

    assert launched is True
    assert database.get_command(record["id"])["status"] == CommandStatus.CANCELED
    assert released_gpu_ids == [0]
