from __future__ import annotations

from cmddock.database import Database
from cmddock.models import CommandStatus


def test_commands_are_listed_newest_first(tmp_path):
    database = Database(tmp_path / "cmddock.db")
    first = database.create_command("echo first", None)
    second = database.create_command("echo second", None)

    records = database.list_commands()

    assert [record["id"] for record in records] == [second["id"], first["id"]]


def test_nonzero_exit_moves_to_error_queue(tmp_path):
    database = Database(tmp_path / "cmddock.db")
    command = database.create_command("false", None)
    claimed = database.claim_next_pending_command()

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
    claimed = database.claim_next_pending_command()

    assert claimed["id"] == first["id"]

    database.requeue_killed(first["id"], -9, "killed_by_signal:SIGKILL")
    next_claimed = database.claim_next_pending_command()

    assert next_claimed["id"] == first["id"]
    pending_ids = [record["id"] for record in database.list_commands(CommandStatus.PENDING)]
    assert second["id"] in pending_ids


def test_running_pid_is_recorded_and_cleared_on_finish(tmp_path):
    database = Database(tmp_path / "cmddock.db")
    command = database.create_command("sleep 10", None)
    claimed = database.claim_next_pending_command()

    assert claimed["id"] == command["id"]

    database.set_running_pid(command["id"], 12345)
    running = database.get_kill_target(command["id"])

    assert running["pid"] == 12345

    finished = database.mark_succeeded(command["id"], 0)
    assert finished["pid"] is None


def test_queue_snapshot_is_newest_first_within_each_status(tmp_path):
    database = Database(tmp_path / "cmddock.db")
    first = database.create_command("echo first", None)
    second = database.create_command("echo second", None)

    snapshot = database.queue_snapshot()

    assert [record["id"] for record in snapshot["pending"]] == [second["id"], first["id"]]
