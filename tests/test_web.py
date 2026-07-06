from __future__ import annotations

from cmddock.web import render_index


def test_group_detail_separates_active_queue_from_terminal_history() -> None:
    html = render_index()

    assert 'id="tasks-body"' in html
    assert 'id="history-body"' in html
    assert "Completed / Canceled" in html
    assert "No queued or active tasks in this group." in html
    assert 'task.status === "succeeded" || task.status === "canceled"' in html
    assert "isKilledPendingTask(task)" in html
    assert "<span>${index + 1}</span>" in html


def test_group_detail_warns_when_group_is_not_schedulable() -> None:
    html = render_index()

    assert 'id="schedule-warning"' in html
    assert "This task group has not been started. Commands will not be scheduled." in html
    assert "This task group is paused. Pending commands will not be scheduled." in html
