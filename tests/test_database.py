from __future__ import annotations

from cmddock.database import Database
from cmddock.models import CommandStatus, QueueMode


def test_commands_are_listed_newest_first(tmp_path):
    database = Database(tmp_path / "cmddock.db")
    first = database.create_command("echo first", None)
    second = database.create_command("echo second", None)

    records = database.list_commands()

    assert [record["id"] for record in records] == [second["id"], first["id"]]


def test_nonzero_exit_moves_to_error_queue(tmp_path):
    database = Database(tmp_path / "cmddock.db")
    command = database.create_command("false", None)
    claimed = database.claim_next_pending_command(QueueMode.SERIAL)

    assert claimed["id"] == command["id"]

    database.mark_error(command["id"], 1, "exited_nonzero:1", "exited_nonzero:1")

    errors = database.list_commands(CommandStatus.ERROR)
    assert len(errors) == 1
    assert errors[0]["id"] == command["id"]
    assert errors[0]["finished_at"] is not None
    assert errors[0]["exit_code"] == 1
    assert errors[0]["pid"] is None


def test_killed_command_requeues_ahead_of_other_pending_commands(tmp_path):
    database = Database(tmp_path / "cmddock.db")
    first = database.create_command("sleep 10", None)
    second = database.create_command("echo second", None)
    claimed = database.claim_next_pending_command(QueueMode.SERIAL)

    assert claimed["id"] == first["id"]

    database.requeue_killed(first["id"], -9, "killed_by_signal:SIGKILL")
    next_claimed = database.claim_next_pending_command(QueueMode.SERIAL)

    assert next_claimed["id"] == first["id"]
    pending_ids = [record["id"] for record in database.list_commands(CommandStatus.PENDING)]
    assert second["id"] in pending_ids


def test_running_pid_is_recorded_and_cleared_on_finish(tmp_path):
    database = Database(tmp_path / "cmddock.db")
    command = database.create_command("sleep 10", None)
    claimed = database.claim_next_pending_command(QueueMode.SERIAL)

    assert claimed["id"] == command["id"]

    database.set_running_pid(command["id"], 12345)
    running = database.get_kill_target(command["id"])

    assert running["pid"] == 12345

    finished = database.mark_succeeded(command["id"], 0)
    assert finished["pid"] is None


def test_unlaunched_running_command_can_be_canceled(tmp_path):
    database = Database(tmp_path / "cmddock.db")
    command = database.create_command("sleep 10", None)
    claimed = database.claim_next_pending_command(QueueMode.SERIAL)

    assert claimed["id"] == command["id"]
    assert claimed["status"] == CommandStatus.RUNNING
    assert claimed["pid"] is None

    canceled = database.cancel_unlaunched_running_command(command["id"])

    assert canceled["status"] == CommandStatus.CANCELED
    assert canceled["finished_at"] is not None
    assert canceled["exit_status"] == "canceled_before_launch"
    assert canceled["pid"] is None
    assert canceled["assigned_gpu_ids"] is None


def test_start_process_if_running_records_pid_and_assigned_gpus(tmp_path):
    database = Database(tmp_path / "cmddock.db")
    command = database.create_command("sleep 10", None)
    database.claim_next_pending_command(QueueMode.SERIAL)

    class Process:
        pid = 12345

    process = database.start_process_if_running(command["id"], "0,1", Process)

    assert process.pid == 12345
    running = database.get_command(command["id"])
    assert running["pid"] == 12345
    assert running["assigned_gpu_ids"] == "0,1"


def test_start_process_if_running_skips_canceled_command(tmp_path):
    database = Database(tmp_path / "cmddock.db")
    command = database.create_command("sleep 10", None)
    database.claim_next_pending_command(QueueMode.SERIAL)
    database.cancel_unlaunched_running_command(command["id"])

    def fail_if_called():
        raise AssertionError("process should not launch after cancellation")

    process = database.start_process_if_running(command["id"], "0", fail_if_called)

    assert process is None


def test_queue_snapshot_is_newest_first_within_each_status(tmp_path):
    database = Database(tmp_path / "cmddock.db")
    first = database.create_command("echo first", None)
    second = database.create_command("echo second", None)

    snapshot = database.queue_snapshot()

    assert [record["id"] for record in snapshot["pending"]] == [second["id"], first["id"]]


def test_default_queue_is_serial(tmp_path):
    database = Database(tmp_path / "cmddock.db")

    command = database.create_command("echo serial", None)

    assert command["queue"] == QueueMode.SERIAL


def test_parallel_queue_can_be_filtered(tmp_path):
    database = Database(tmp_path / "cmddock.db")
    serial = database.create_command("echo serial", None, QueueMode.SERIAL)
    parallel = database.create_command("echo parallel", None, QueueMode.PARALLEL)

    serial_records = database.list_commands(queue=QueueMode.SERIAL)
    parallel_records = database.list_commands(queue=QueueMode.PARALLEL)

    assert [record["id"] for record in serial_records] == [serial["id"]]
    assert [record["id"] for record in parallel_records] == [parallel["id"]]


def test_serial_and_parallel_claims_are_isolated(tmp_path):
    database = Database(tmp_path / "cmddock.db")
    serial = database.create_command("echo serial", None, QueueMode.SERIAL)
    parallel = database.create_command("echo parallel", None, QueueMode.PARALLEL)

    claimed_parallel = database.claim_next_pending_command(QueueMode.PARALLEL)
    claimed_serial = database.claim_next_pending_command(QueueMode.SERIAL)

    assert claimed_parallel["id"] == parallel["id"]
    assert claimed_serial["id"] == serial["id"]
