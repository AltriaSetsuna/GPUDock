from __future__ import annotations

import sqlite3

import pytest

from cmddock.database import Database
from cmddock.models import CommandStatus, GroupExecutionState, GroupStatus


def _start_group_for_command(database: Database, command: dict) -> None:
    database.start_task_group(command["group_id"])


def test_commands_are_listed_newest_first(tmp_path):
    database = Database(tmp_path / "cmddock.db")
    first = database.create_command("echo first", None)
    second = database.create_command("echo second", None)

    records = database.list_commands()

    assert [record["id"] for record in records] == [second["id"], first["id"]]
    assert records[0]["group_name"] == "default"


def test_task_groups_are_created_and_listed_by_position(tmp_path):
    database = Database(tmp_path / "cmddock.db")
    first = database.create_task_group("first")
    second = database.create_task_group("second", "experiment batch")
    command = database.create_command("echo run", None, group_id=first["id"])

    groups = database.list_task_groups()
    ids = [group["id"] for group in groups]

    assert ids == [database.get_or_create_task_group("default")["id"], first["id"], second["id"]]
    assert groups[0]["position"] == 1
    assert groups[1]["position"] == 2
    assert groups[1]["execution_state"] == GroupExecutionState.DRAFT
    assert groups[1]["status"] == GroupStatus.DRAFT
    assert groups[1]["pending_count"] == 1
    assert groups[1]["current_command_id"] == command["id"]
    assert groups[2]["position"] == 3
    assert groups[2]["description"] == "experiment batch"
    assert groups[2]["status"] == GroupStatus.EMPTY


def test_task_group_names_are_unique_case_insensitively(tmp_path):
    database = Database(tmp_path / "cmddock.db")

    database.create_task_group("Alpha")

    with pytest.raises(ValueError, match="already exists"):
        database.create_task_group("alpha")


def test_task_groups_can_be_reordered(tmp_path):
    database = Database(tmp_path / "cmddock.db")
    default = database.get_or_create_task_group("default")
    first = database.create_task_group("first")
    second = database.create_task_group("second")

    reordered = database.reorder_task_groups([second["id"], default["id"], first["id"]])

    assert [group["id"] for group in reordered] == [second["id"], default["id"], first["id"]]
    assert [group["position"] for group in reordered] == [1, 2, 3]


def test_task_group_order_controls_scheduler_priority(tmp_path):
    database = Database(tmp_path / "cmddock.db")
    default = database.get_or_create_task_group("default")
    group_a = database.create_task_group("group-a")
    group_b = database.create_task_group("group-b")
    a_command = database.create_command("echo a", None, group_id=group_a["id"])
    b_command = database.create_command("echo b", None, group_id=group_b["id"])
    database.reorder_task_groups([group_b["id"], group_a["id"], default["id"]])
    database.start_task_group(group_a["id"])
    database.start_task_group(group_b["id"])

    first_claim = database.claim_next_pending_command()
    database.mark_succeeded(b_command["id"], 0)
    second_claim = database.claim_next_pending_command()

    assert first_claim["id"] == b_command["id"]
    assert second_claim["id"] == a_command["id"]


def test_draft_group_is_not_claimed_until_started(tmp_path):
    database = Database(tmp_path / "cmddock.db")
    command = database.create_command("echo wait", None)

    assert database.claim_next_pending_command() is None

    started = database.start_task_group(command["group_id"])
    claimed = database.claim_next_pending_command()

    assert started["execution_state"] == GroupExecutionState.RUNNING
    assert started["status"] == GroupStatus.PENDING
    assert claimed["id"] == command["id"]


def test_pending_commands_can_be_reordered_in_draft_group(tmp_path):
    database = Database(tmp_path / "cmddock.db")
    group = database.create_task_group("ordered")
    first = database.create_command("echo first", None, group_id=group["id"])
    second = database.create_command("echo second", None, group_id=group["id"])
    third = database.create_command("echo third", None, group_id=group["id"])

    reordered = database.reorder_pending_commands(
        group["id"],
        [third["id"], first["id"], second["id"]],
    )
    database.start_task_group(group["id"])
    claimed = database.claim_next_pending_command()

    assert [record["id"] for record in reordered] == [third["id"], first["id"], second["id"]]
    assert [record["position"] for record in reordered] == [1, 2, 3]
    assert claimed["id"] == third["id"]


def test_nonzero_exit_moves_to_error_and_blocks_group(tmp_path):
    database = Database(tmp_path / "cmddock.db")
    command = database.create_command("false", None)
    _start_group_for_command(database, command)
    claimed = database.claim_next_pending_command()

    assert claimed["id"] == command["id"]

    database.mark_error(command["id"], 1, "exited_nonzero:1", "exited_nonzero:1")

    errors = database.list_commands(CommandStatus.ERROR)
    group = database.get_task_group(command["group_id"])

    assert len(errors) == 1
    assert errors[0]["id"] == command["id"]
    assert errors[0]["finished_at"] is not None
    assert errors[0]["exit_code"] == 1
    assert errors[0]["pid"] is None
    assert group["status"] == GroupStatus.BLOCKED


def test_killed_command_requeues_ahead_and_pauses_group(tmp_path):
    database = Database(tmp_path / "cmddock.db")
    first = database.create_command("sleep 10", None)
    second = database.create_command("echo second", None)
    _start_group_for_command(database, first)
    claimed = database.claim_next_pending_command()

    assert claimed["id"] == first["id"]

    database.requeue_killed(first["id"], -9, "killed_by_signal:SIGKILL")
    group = database.get_task_group(first["group_id"])
    blocked_claim = database.claim_next_pending_command()

    assert group["execution_state"] == GroupExecutionState.PAUSED
    assert group["status"] == GroupStatus.PAUSED
    assert group["manual_start_required"] is True
    assert blocked_claim is None
    pending_ids = [record["id"] for record in database.list_commands(CommandStatus.PENDING)]
    assert second["id"] in pending_ids

    database.start_task_group(first["group_id"])
    next_claimed = database.claim_next_pending_command()

    assert next_claimed["id"] == first["id"]


def test_killed_pending_command_can_be_retried_without_starting_group(tmp_path):
    database = Database(tmp_path / "cmddock.db")
    command = database.create_command("sleep 10", None)
    _start_group_for_command(database, command)
    database.claim_next_pending_command()
    database.requeue_killed(command["id"], -15, "killed_by_signal:SIGTERM")

    retried = database.retry_command(command["id"])
    group = database.get_task_group(command["group_id"])

    assert retried["status"] == CommandStatus.PENDING
    assert retried["exit_status"] is None
    assert retried["exit_code"] is None
    assert retried["error_message"] is None
    assert retried["run_after_id"] is None
    assert group["execution_state"] == GroupExecutionState.PAUSED
    assert group["manual_start_required"] is True
    assert database.claim_next_pending_command() is None


def test_retry_error_command_requires_manual_group_start(tmp_path):
    database = Database(tmp_path / "cmddock.db")
    command = database.create_command("false", None)
    _start_group_for_command(database, command)
    database.claim_next_pending_command()
    database.mark_error(command["id"], 1, "exited_nonzero:1", "boom")

    retried = database.retry_command(command["id"])
    group = database.get_task_group(command["group_id"])

    assert retried["status"] == CommandStatus.PENDING
    assert group["execution_state"] == GroupExecutionState.PAUSED
    assert group["manual_start_required"] is True
    assert database.claim_next_pending_command() is None


def test_retry_killed_pending_command_forces_group_to_remain_paused(tmp_path):
    database = Database(tmp_path / "cmddock.db")
    command = database.create_command("sleep 10", None)
    _start_group_for_command(database, command)
    database.claim_next_pending_command()
    database.requeue_killed(command["id"], -15, "killed_by_signal:SIGTERM")
    database.start_task_group(command["group_id"])

    retried = database.retry_command(command["id"])
    group = database.get_task_group(command["group_id"])

    assert retried["status"] == CommandStatus.PENDING
    assert group["execution_state"] == GroupExecutionState.PAUSED
    assert group["manual_start_required"] is True
    assert database.claim_next_pending_command() is None


def test_manual_start_required_blocks_claim_until_group_is_started(tmp_path):
    database = Database(tmp_path / "cmddock.db")
    command = database.create_command("sleep 10", None)
    _start_group_for_command(database, command)
    database.claim_next_pending_command()
    database.requeue_killed(command["id"], -15, "killed_by_signal:SIGTERM")
    database.retry_command(command["id"])

    blocked_claim = database.claim_next_pending_command()
    started = database.start_task_group(command["group_id"])
    claimed = database.claim_next_pending_command()

    assert blocked_claim is None
    assert started["manual_start_required"] is False
    assert claimed["id"] == command["id"]


def test_running_pid_is_recorded_and_cleared_on_finish(tmp_path):
    database = Database(tmp_path / "cmddock.db")
    command = database.create_command("sleep 10", None)
    _start_group_for_command(database, command)
    claimed = database.claim_next_pending_command()

    assert claimed["id"] == command["id"]

    database.set_running_pid(command["id"], 12345)
    running = database.get_kill_target(command["id"])

    assert running["pid"] == 12345

    finished = database.mark_succeeded(command["id"], 0)
    assert finished["pid"] is None


def test_unlaunched_running_command_kill_requeues_and_pauses_group(tmp_path):
    database = Database(tmp_path / "cmddock.db")
    command = database.create_command("sleep 10", None)
    _start_group_for_command(database, command)
    claimed = database.claim_next_pending_command()

    assert claimed["id"] == command["id"]
    assert claimed["status"] == CommandStatus.RUNNING
    assert claimed["pid"] is None

    killed = database.requeue_unlaunched_killed(command["id"])
    group = database.get_task_group(command["group_id"])

    assert killed["status"] == CommandStatus.PENDING
    assert killed["finished_at"] is not None
    assert killed["exit_status"] == "killed_before_launch"
    assert killed["pid"] is None
    assert killed["assigned_gpu_ids"] is None
    assert killed["run_after_id"] == command["id"]
    assert group["execution_state"] == GroupExecutionState.PAUSED
    assert group["manual_start_required"] is True
    assert database.claim_next_pending_command() is None


def test_start_process_if_running_records_pid_and_assigned_gpus(tmp_path):
    database = Database(tmp_path / "cmddock.db")
    command = database.create_command("sleep 10", None)
    _start_group_for_command(database, command)
    database.claim_next_pending_command()

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
    _start_group_for_command(database, command)
    database.claim_next_pending_command()
    database.cancel_unlaunched_running_command(command["id"])

    def fail_if_called():
        raise AssertionError("process should not launch after cancellation")

    process = database.start_process_if_running(command["id"], "0", fail_if_called)

    assert process is None


def test_scheduler_snapshot_is_newest_first_within_each_status(tmp_path):
    database = Database(tmp_path / "cmddock.db")
    first = database.create_command("echo first", None)
    second = database.create_command("echo second", None)

    snapshot = database.scheduler_snapshot()

    assert [record["id"] for record in snapshot["pending"]] == [second["id"], first["id"]]


def test_group_claims_are_serial_within_group_and_parallel_between_groups(tmp_path):
    database = Database(tmp_path / "cmddock.db")
    group_a = database.create_task_group("group-a")
    group_b = database.create_task_group("group-b")
    a_first = database.create_command("echo a1", None, group_id=group_a["id"])
    a_second = database.create_command("echo a2", None, group_id=group_a["id"])
    b_first = database.create_command("echo b1", None, group_id=group_b["id"])
    database.start_task_group(group_a["id"])
    database.start_task_group(group_b["id"])

    claimed_a = database.claim_next_pending_command()
    claimed_b = database.claim_next_pending_command()
    no_more = database.claim_next_pending_command()

    assert {claimed_a["id"], claimed_b["id"]} == {a_first["id"], b_first["id"]}
    assert no_more is None

    database.mark_succeeded(a_first["id"], 0)
    claimed_a_second = database.claim_next_pending_command()

    assert claimed_a_second["id"] == a_second["id"]


def test_error_blocks_later_commands_in_same_group(tmp_path):
    database = Database(tmp_path / "cmddock.db")
    group = database.create_task_group("blocked")
    first = database.create_command("false", None, group_id=group["id"])
    database.create_command("echo later", None, group_id=group["id"])
    database.start_task_group(group["id"])
    claimed = database.claim_next_pending_command()

    assert claimed["id"] == first["id"]

    database.mark_error(first["id"], 1, "exited_nonzero:1", "boom")

    assert database.claim_next_pending_command() is None


def test_task_group_delete_requires_all_commands_terminal_ok_or_canceled(tmp_path):
    database = Database(tmp_path / "cmddock.db")
    group = database.create_task_group("cleanup")
    succeeded = database.create_command("echo ok", None, group_id=group["id"])
    canceled = database.create_command("echo skip", None, group_id=group["id"])
    running = database.create_command("sleep 10", None, group_id=group["id"])

    database.mark_succeeded(succeeded["id"], 0)
    database.cancel_pending_command(canceled["id"])

    try:
        database.delete_task_group(group["id"])
    except ValueError as exc:
        assert "succeeded or canceled" in str(exc)
    else:
        raise AssertionError("group deletion should reject non-terminal commands")

    database.cancel_pending_command(running["id"])
    deleted = database.delete_task_group(group["id"])

    assert deleted["archived_at"] is not None
    assert deleted["status"] == GroupStatus.ARCHIVED
    assert group["id"] not in [item["id"] for item in database.list_task_groups()]


def test_existing_queue_database_is_migrated_to_default_group(tmp_path):
    db_path = tmp_path / "cmddock.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE commands (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                command TEXT NOT NULL,
                cwd TEXT,
                queue TEXT NOT NULL DEFAULT 'serial',
                status TEXT NOT NULL,
                submitted_at TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT,
                exit_code INTEGER,
                exit_status TEXT,
                pid INTEGER,
                gpu_count INTEGER,
                assigned_gpu_ids TEXT,
                stdout_path TEXT,
                stderr_path TEXT,
                error_message TEXT,
                run_after_id INTEGER
            )
            """
        )
        conn.execute(
            """
            INSERT INTO commands (command, cwd, queue, status, submitted_at)
            VALUES ('echo old', NULL, 'serial', 'pending', '2026-01-01T00:00:00+00:00')
            """
        )

    database = Database(db_path)
    commands = database.list_commands()

    assert commands[0]["group_name"] == "default"
    default_group = database.get_or_create_task_group("default")
    assert commands[0]["group_id"] == default_group["id"]
    assert commands[0]["position"] == 1
    assert default_group["position"] == 1
    assert default_group["manual_start_required"] is False
