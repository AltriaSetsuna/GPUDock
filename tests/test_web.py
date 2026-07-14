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
    assert 'task.exit_status === "killed_before_launch"' in html
    assert "<span>${index + 1}</span>" in html


def test_group_dashboard_supports_reordering_and_wide_layout() -> None:
    html = render_index()

    assert 'class="groups-table"' in html
    assert "width: min(1720px, calc(100vw - 24px))" in html
    assert 'data-action="move-group-up"' in html
    assert 'data-action="move-group-down"' in html
    assert 'api("/groups/order"' in html
    assert "currentGroups = groups" in html


def test_group_detail_warns_when_group_is_not_schedulable() -> None:
    html = render_index()
    manual_restart_warning = (
        "This task group requires a manual restart. Pending commands will not be scheduled."
    )

    assert 'id="schedule-warning"' in html
    assert "This task group has not been started. Commands will not be scheduled." in html
    assert "This task group is paused. Pending commands will not be scheduled." in html
    assert manual_restart_warning in html
    assert (
        "This task group has started successfully. Pending commands are waiting for scheduling."
        in html
    )
    assert 'group.execution_state === "draft"' in html
    assert 'group.execution_state === "paused"' in html
    assert 'group.execution_state === "running"' in html
    assert 'group.status === "completed"' in html


def test_dashboard_does_not_show_group_or_task_ids() -> None:
    html = render_index()

    assert "<th>ID</th>" not in html
    assert "<td>${group.id}</td>" not in html
    assert "<td>${task.id}</td>" not in html
    assert "(#${group.id})" not in html
    assert "Task ${id} Logs" not in html
    assert "Task ${task.id} submitted" not in html


def test_dashboard_has_lower_left_gpu_status_widget() -> None:
    html = render_index()

    assert 'id="gpu-widget"' in html
    assert 'id="gpu-resource-buttons"' in html
    assert 'id="gpu-status-output"' in html
    assert "/gpu/resources" in html
    assert "/gpu/status?resource=" in html
    assert "setInterval(refreshGpuStatus, 3000)" in html
    assert 'class="left-rail"' in html
    assert "position: static;" in html
    assert "width: 100%;" in html
    assert "margin: 0;" in html
    assert "Loading task groups..." in html
    assert "isExpanded && resource === selectedGpuResource" in html
    assert "let gpuStatusRequestId = 0;" in html
    assert "Loading ${resource} GPU status..." in html
    assert "requestId !== gpuStatusRequestId || resource !== selectedGpuResource" in html
    assert "await refreshGpuStatus(true)" in html
    assert 'id="gpu-widget-close"' in html
    assert 'gpuWidget.classList.remove("expanded")' in html
    assert "event.stopPropagation()" in html


def test_dashboard_avoids_nullish_coalescing_for_older_browsers() -> None:
    html = render_index()

    assert "??" not in html
    assert "?." not in html
    assert "task.min_idle_seconds == null ? 120 : task.min_idle_seconds" in html


def test_dashboard_escapes_database_values_before_using_inner_html() -> None:
    html = render_index()

    assert "escapeHtml(group.name)" in html
    assert 'escapeHtml(group.current_command || "")' in html
    assert "escapeHtml(task.command)" in html
    assert "escapeHtml(taskGpu(task))" in html
