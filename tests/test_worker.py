from __future__ import annotations

import time

from cmddock.database import Database
from cmddock.models import CommandStatus, QueueMode
from cmddock.worker import CommandWorker, ParallelDispatcher


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


def test_serial_worker_and_parallel_dispatcher_process_isolated_queues(tmp_path):
    database = Database(tmp_path / "cmddock.db")
    logs_dir = tmp_path / "logs"
    serial = database.create_command("printf serial", None, QueueMode.SERIAL)
    parallel_one = database.create_command("printf parallel-one", None, QueueMode.PARALLEL)
    parallel_two = database.create_command("printf parallel-two", None, QueueMode.PARALLEL)

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
