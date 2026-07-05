from __future__ import annotations

import time

from cmddock.database import Database
from cmddock.gpu import GPUReservation
from cmddock.models import CommandStatus, QueueMode
from cmddock.worker import CommandRunner, CommandWorker, ParallelDispatcher


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


def test_serial_worker_and_parallel_dispatcher_process_isolated_queues(tmp_path, monkeypatch):
    database = Database(tmp_path / "cmddock.db")
    logs_dir = tmp_path / "logs"
    monkeypatch.setattr(
        "cmddock.worker.reserve_idle_gpus",
        lambda gpu_count: GPUReservation([0], [0, 1, 2]),
    )
    monkeypatch.setattr("cmddock.worker.release_reserved_gpus", lambda gpu_ids: None)
    monkeypatch.setattr("cmddock.worker.send_launch_email_async", lambda **kwargs: None)

    serial_script = _write_script(tmp_path, "serial.sh", "printf serial")
    parallel_one_script = _write_script(tmp_path, "parallel-one.sh", "printf parallel-one")
    parallel_two_script = _write_script(tmp_path, "parallel-two.sh", "printf parallel-two")

    serial = database.create_command(str(serial_script), None, QueueMode.SERIAL, 1)
    parallel_one = database.create_command(str(parallel_one_script), None, QueueMode.PARALLEL, 1)
    parallel_two = database.create_command(str(parallel_two_script), None, QueueMode.PARALLEL, 1)

    serial_worker = CommandWorker(database, logs_dir, poll_interval_seconds=0.05)
    parallel_dispatcher = ParallelDispatcher(database, logs_dir, poll_interval_seconds=0.05)
    serial_worker.start()
    parallel_dispatcher.start()
    try:
        _wait_for_statuses(
            database,
            {
                serial["id"]: CommandStatus.SUCCEEDED,
                parallel_one["id"]: CommandStatus.SUCCEEDED,
                parallel_two["id"]: CommandStatus.SUCCEEDED,
            },
        )
    finally:
        serial_worker.stop()
        parallel_dispatcher.stop()

    serial_records = database.list_commands(queue=QueueMode.SERIAL)
    parallel_records = database.list_commands(queue=QueueMode.PARALLEL)

    assert [record["id"] for record in serial_records] == [serial["id"]]
    assert {record["id"] for record in parallel_records} == {parallel_one["id"], parallel_two["id"]}
    assert (logs_dir / f"{serial['id']}.stdout.log").read_text() == "serial"
    assert (logs_dir / f"{parallel_one['id']}.stdout.log").read_text() == "parallel-one"
    assert (logs_dir / f"{parallel_two['id']}.stdout.log").read_text() == "parallel-two"


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
    record = database.create_command(command, None, QueueMode.SERIAL, 1)
    claimed = database.claim_next_pending_command(QueueMode.SERIAL)

    launched = CommandRunner(database, logs_dir).run_one(claimed)

    assert launched is True
    assert database.get_command(record["id"])["status"] == CommandStatus.SUCCEEDED
    assert (logs_dir / f"{record['id']}.stdout.log").read_text() == "/home/data.json|3|1"


def test_command_runner_does_not_launch_after_prelaunch_cancel(tmp_path, monkeypatch):
    database = Database(tmp_path / "cmddock.db")
    logs_dir = tmp_path / "logs"
    released_gpu_ids = []

    script = _write_script(tmp_path, "cancel-before-launch.sh", "printf should-not-run")
    record = database.create_command(str(script), None, QueueMode.SERIAL, 1)
    claimed = database.claim_next_pending_command(QueueMode.SERIAL)

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
