from __future__ import annotations


def render_index() -> str:
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>GPUDock</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f5f7fa;
      --panel: #ffffff;
      --panel-muted: #f0f3f7;
      --border: #d8dee8;
      --text: #16202f;
      --muted: #697386;
      --accent: #146c94;
      --accent-strong: #0f526f;
      --danger: #b42318;
      --warning: #946200;
      --ok: #16794c;
      --shadow: 0 10px 30px rgb(15 23 42 / 8%);
    }

    * { box-sizing: border-box; }

    body {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family:
        Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      line-height: 1.5;
    }

    header {
      border-bottom: 1px solid var(--border);
      background: var(--panel);
    }

    .topbar {
      width: min(1280px, calc(100vw - 32px));
      margin: 0 auto;
      padding: 18px 0;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
    }

    .brand {
      display: flex;
      flex-direction: column;
      gap: 2px;
    }

    h1 {
      margin: 0;
      font-size: 22px;
      line-height: 1.1;
      letter-spacing: 0;
    }

    .subtitle {
      color: var(--muted);
      font-size: 13px;
    }

    .status-pill {
      border: 1px solid var(--border);
      border-radius: 999px;
      padding: 7px 11px;
      color: var(--muted);
      background: var(--panel-muted);
      font-size: 13px;
      white-space: nowrap;
    }

    main {
      width: min(1280px, calc(100vw - 32px));
      margin: 24px auto 40px;
      display: grid;
      grid-template-columns: minmax(320px, 390px) minmax(0, 1fr);
      gap: 20px;
      align-items: start;
    }

    section {
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 8px;
      box-shadow: var(--shadow);
    }

    .section-header {
      min-height: 64px;
      padding: 16px 18px;
      border-bottom: 1px solid var(--border);
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
    }

    h2 {
      margin: 0;
      font-size: 15px;
      letter-spacing: 0;
    }

    .panel-body { padding: 18px; }

    label {
      display: block;
      color: var(--muted);
      font-size: 13px;
      margin-bottom: 7px;
    }

    input, textarea {
      width: 100%;
      border: 1px solid var(--border);
      border-radius: 6px;
      background: #fff;
      color: var(--text);
      font: inherit;
      font-size: 14px;
      padding: 10px 11px;
      outline: none;
    }

    input:focus, textarea:focus {
      border-color: var(--accent);
      box-shadow: 0 0 0 3px rgb(20 108 148 / 16%);
    }

    textarea {
      min-height: 96px;
      resize: vertical;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 12px;
    }

    .field { margin-bottom: 14px; }

    .row {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 12px;
    }

    button {
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 9px 11px;
      background: var(--panel);
      color: var(--text);
      cursor: pointer;
      font: inherit;
      font-size: 13px;
    }

    button:hover {
      border-color: #a9b4c4;
      background: #f8fafc;
    }

    button.primary {
      border-color: var(--accent);
      background: var(--accent);
      color: #fff;
      font-weight: 650;
    }

    button.primary:hover {
      border-color: var(--accent-strong);
      background: var(--accent-strong);
    }

    button.danger {
      color: var(--danger);
      border-color: #f1b8b2;
    }

    button:disabled {
      opacity: 0.55;
      cursor: not-allowed;
    }

    .actions, .toolbar, .task-actions {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      align-items: center;
    }

    .notice {
      display: none;
      border-radius: 6px;
      margin-top: 14px;
      padding: 10px 11px;
      font-size: 13px;
      border: 1px solid var(--border);
      background: var(--panel-muted);
      color: var(--muted);
    }

    .notice.show { display: block; }
    .notice.error { border-color: #f1b8b2; color: var(--danger); background: #fff4f2; }
    .notice.ok { border-color: #acd7c0; color: var(--ok); background: #f0fbf5; }

    .schedule-warning {
      display: none;
      margin-bottom: 14px;
      color: var(--danger);
      font-weight: 650;
      font-size: 14px;
    }

    .schedule-warning.show { display: block; }

    .table-wrap { overflow-x: auto; }

    .history-block {
      border-top: 1px solid var(--border);
      margin-top: 4px;
    }

    .history-block .section-header {
      min-height: 52px;
      background: #fbfcfe;
    }

    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
    }

    th, td {
      border-bottom: 1px solid var(--border);
      padding: 10px 9px;
      text-align: left;
      vertical-align: top;
      white-space: nowrap;
    }

    th {
      color: var(--muted);
      font-weight: 650;
      background: #fbfcfe;
    }

    td.command, td.current {
      white-space: normal;
      min-width: 260px;
      max-width: 520px;
      word-break: break-word;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 12px;
    }

    .badge {
      display: inline-flex;
      align-items: center;
      border-radius: 999px;
      padding: 3px 8px;
      border: 1px solid var(--border);
      background: var(--panel-muted);
      color: var(--muted);
      font-size: 12px;
      text-transform: lowercase;
    }

    .badge.running { color: var(--accent); border-color: #a8d4e5; background: #eef8fc; }
    .badge.succeeded, .badge.completed {
      color: var(--ok);
      border-color: #acd7c0;
      background: #f0fbf5;
    }

    .badge.error, .badge.blocked {
      color: var(--danger);
      border-color: #f1b8b2;
      background: #fff4f2;
    }
    .badge.pending { color: var(--warning); border-color: #ead197; background: #fff9e8; }
    .badge.canceled, .badge.empty, .badge.draft, .badge.paused { color: var(--muted); }

    .empty {
      padding: 24px;
      text-align: center;
      color: var(--muted);
      font-size: 14px;
    }

    .hidden { display: none !important; }

    .detail-title {
      display: flex;
      flex-direction: column;
      gap: 2px;
      min-width: 0;
    }

    .detail-title .subtitle {
      max-width: 560px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .modal-backdrop {
      display: none;
      position: fixed;
      inset: 0;
      background: rgb(15 23 42 / 52%);
      padding: 28px;
      align-items: center;
      justify-content: center;
    }

    .modal-backdrop.show { display: flex; }

    .modal {
      width: min(900px, 100%);
      max-height: min(760px, calc(100vh - 48px));
      background: var(--panel);
      border-radius: 8px;
      border: 1px solid var(--border);
      box-shadow: var(--shadow);
      display: flex;
      flex-direction: column;
    }

    .modal .panel-body { overflow: auto; }

    pre {
      margin: 0;
      white-space: pre-wrap;
      word-break: break-word;
      font-size: 12px;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    }

    @media (max-width: 980px) {
      main { grid-template-columns: 1fr; }
      .row { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <header>
    <div class="topbar">
      <div class="brand">
        <h1>GPUDock</h1>
        <div class="subtitle">Task groups run serially; groups run in parallel.</div>
      </div>
      <div id="health" class="status-pill">Checking service...</div>
    </div>
  </header>

  <main>
    <section>
      <div class="section-header">
        <h2>Create Group</h2>
      </div>
      <div class="panel-body">
        <form id="group-form">
          <div class="field">
            <label for="group-name">Group name</label>
            <input id="group-name" name="name" placeholder="qwen sweep" required />
          </div>
          <div class="field">
            <label for="group-description">Description</label>
            <textarea id="group-description" name="description" placeholder="optional"></textarea>
          </div>
          <div class="actions">
            <button class="primary" type="submit">Create Group</button>
            <button type="button" id="refresh-button">Refresh</button>
          </div>
          <div id="notice" class="notice"></div>
        </form>
      </div>
    </section>

    <section id="groups-section">
      <div class="section-header">
        <h2>Task Groups</h2>
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>ID</th>
              <th>Status</th>
              <th>Name</th>
              <th>Counts</th>
              <th>Current</th>
              <th>Updated</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody id="groups-body"></tbody>
        </table>
        <div id="groups-empty" class="empty">No task groups yet.</div>
      </div>
    </section>

    <section id="detail-section" class="hidden">
      <div class="section-header">
        <div class="detail-title">
          <h2 id="detail-name">Group</h2>
          <div id="detail-description" class="subtitle"></div>
        </div>
        <div class="toolbar">
          <button type="button" id="back-button">Back</button>
          <button type="button" class="primary" id="start-group-button">Start Group</button>
          <button type="button" id="pause-group-button">Pause Group</button>
          <button type="button" class="danger" id="delete-group-button">Delete Group</button>
        </div>
      </div>
      <div class="panel-body">
        <div id="schedule-warning" class="schedule-warning"></div>
        <form id="submit-form">
          <div class="field">
            <label for="script-path">Script command</label>
            <input
              id="script-path"
              name="command"
              placeholder="DATA_PATH=/home/data.json bash /home/user/jobs/train.sh"
              required
            />
          </div>
          <div class="field">
            <label for="cwd">Working directory</label>
            <input id="cwd" name="cwd" placeholder="optional" />
          </div>
          <div class="field">
            <label for="min-idle-seconds">Min idle seconds</label>
            <input
              id="min-idle-seconds"
              name="min_idle_seconds"
              type="number"
              min="0"
              max="86400"
              step="1"
              value="120"
            />
          </div>
          <div class="actions">
            <button class="primary" type="submit">Submit To Group</button>
          </div>
        </form>
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>ID</th>
              <th>Order</th>
              <th>Status</th>
              <th>GPU</th>
              <th>Idle</th>
              <th>Script</th>
              <th>Submitted</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody id="tasks-body"></tbody>
        </table>
        <div id="tasks-empty" class="empty">No queued or active tasks in this group.</div>
      </div>
      <div class="history-block">
        <div class="section-header">
          <h2>Completed / Canceled</h2>
        </div>
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>ID</th>
                <th>Status</th>
                <th>GPU</th>
                <th>Idle</th>
                <th>Script</th>
                <th>Finished</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody id="history-body"></tbody>
          </table>
          <div id="history-empty" class="empty">No completed or canceled tasks yet.</div>
        </div>
      </div>
    </section>
  </main>

  <div id="logs-modal" class="modal-backdrop" role="dialog" aria-modal="true">
    <div class="modal">
      <div class="section-header">
        <h2 id="logs-title">Task Logs</h2>
        <button type="button" id="close-logs">Close</button>
      </div>
      <div class="panel-body">
        <label>stdout</label>
        <pre id="stdout"></pre>
        <div style="height: 18px"></div>
        <label>stderr</label>
        <pre id="stderr"></pre>
      </div>
    </div>
  </div>

  <script>
    const groupForm = document.querySelector("#group-form");
    const submitForm = document.querySelector("#submit-form");
    const notice = document.querySelector("#notice");
    const groupsBody = document.querySelector("#groups-body");
    const tasksBody = document.querySelector("#tasks-body");
    const historyBody = document.querySelector("#history-body");
    const groupsEmpty = document.querySelector("#groups-empty");
    const tasksEmpty = document.querySelector("#tasks-empty");
    const historyEmpty = document.querySelector("#history-empty");
    const health = document.querySelector("#health");
    const logsModal = document.querySelector("#logs-modal");
    const groupsSection = document.querySelector("#groups-section");
    const detailSection = document.querySelector("#detail-section");
    const scheduleWarning = document.querySelector("#schedule-warning");
    let selectedGroup = null;
    let currentTasks = [];

    function showNotice(message, type = "") {
      notice.textContent = message;
      notice.className = `notice show ${type}`;
    }

    function formatTime(value) {
      if (!value) return "";
      return new Date(value).toLocaleString();
    }

    function taskGpu(task) {
      if (task.assigned_gpu_ids) return task.assigned_gpu_ids;
      if (task.gpu_count) return `needs ${task.gpu_count}`;
      return "non-GPU";
    }

    function taskIdle(task) {
      if (!task.gpu_count) return "ignored";
      return `${task.min_idle_seconds ?? 120}s`;
    }

    function isTerminalTask(task) {
      return task.status === "succeeded" || task.status === "canceled";
    }

    function taskActivityTime(task) {
      return new Date(task.finished_at || task.started_at || task.submitted_at).getTime();
    }

    function isKilledPendingTask(task) {
      return task.status === "pending"
        && task.exit_status
        && (
          task.exit_status.startsWith("killed_by_signal:")
          || task.exit_status === "killed_before_launch"
        );
    }

    function groupCounts(group) {
      return [
        `run ${group.running_count}`,
        `pend ${group.pending_count}`,
        `ok ${group.succeeded_count}`,
        `err ${group.error_count}`,
        `cancel ${group.canceled_count}`,
      ].join(" / ");
    }

    async function api(path, options = {}) {
      const response = await fetch(path, {
        headers: { "content-type": "application/json" },
        ...options,
      });
      const text = await response.text();
      let data = null;
      try {
        data = text ? JSON.parse(text) : null;
      } catch {
        data = text;
      }
      if (!response.ok) {
        const detail = data && data.detail ? data.detail : text || response.statusText;
        throw new Error(detail);
      }
      return data;
    }

    async function refreshHealth() {
      try {
        await api("/health");
        health.textContent = "Service online";
      } catch {
        health.textContent = "Service unavailable";
      }
    }

    async function refreshGroups() {
      const data = await api("/groups");
      renderGroups(data.groups || []);
    }

    async function refreshSelectedGroup() {
      if (!selectedGroup) return;
      selectedGroup = await api(`/groups/${selectedGroup.id}`);
      renderDetailHeader(selectedGroup);
      const data = await api(`/groups/${selectedGroup.id}/commands`);
      renderTasks(data.commands || []);
    }

    function renderGroups(groups) {
      groupsBody.innerHTML = "";
      groupsEmpty.style.display = groups.length ? "none" : "block";
      for (const group of groups) {
        const canDelete = group.status === "completed" || group.status === "empty"
          ? ""
          : "disabled";
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td>${group.id}</td>
          <td><span class="badge ${group.status}">${group.status}</span></td>
          <td>${group.name}</td>
          <td>${groupCounts(group)}</td>
          <td class="current">${group.current_command || ""}</td>
          <td>${formatTime(group.latest_activity_at)}</td>
          <td>
            <div class="task-actions">
              <button data-action="open-group" data-id="${group.id}">Open</button>
              <button class="danger" data-action="delete-group" data-id="${group.id}" ${canDelete}>
                Delete
              </button>
            </div>
          </td>
        `;
        groupsBody.appendChild(tr);
      }
    }

    function renderDetailHeader(group) {
      document.querySelector("#detail-name").textContent = `${group.name} (#${group.id})`;
      const state = group.execution_state || group.status;
      document.querySelector("#detail-description").textContent =
        `${state}${group.description ? ` - ${group.description}` : ""}`;
      document.querySelector("#start-group-button").disabled = !(
        (group.execution_state === "draft" || group.execution_state === "paused")
        && group.pending_count > 0
      );
      document.querySelector("#pause-group-button").disabled = group.execution_state !== "running";
      const submitButton = submitForm.querySelector("button[type='submit']");
      submitButton.disabled = group.execution_state !== "draft";
      document.querySelector("#delete-group-button").disabled = !(
        group.status === "completed" || group.status === "empty"
      );
      if (group.execution_state === "draft") {
        scheduleWarning.textContent =
          "This task group has not been started. Commands will not be scheduled.";
        scheduleWarning.classList.add("show");
      } else if (group.execution_state === "paused") {
        scheduleWarning.textContent = group.manual_start_required
          ? "This task group requires a manual restart. Pending commands will not be scheduled."
          : "This task group is paused. Pending commands will not be scheduled.";
        scheduleWarning.classList.add("show");
      } else {
        scheduleWarning.textContent = "";
        scheduleWarning.classList.remove("show");
      }
    }

    function renderTasks(tasks) {
      const activeTasks = tasks.filter((task) => !isTerminalTask(task));
      const historyTasks = tasks
        .filter(isTerminalTask)
        .sort((left, right) => taskActivityTime(right) - taskActivityTime(left));
      currentTasks = activeTasks;
      tasksBody.innerHTML = "";
      historyBody.innerHTML = "";
      tasksEmpty.style.display = activeTasks.length ? "none" : "block";
      historyEmpty.style.display = historyTasks.length ? "none" : "block";
      const pendingTasks = activeTasks.filter((task) => task.status === "pending");
      for (const [index, task] of activeTasks.entries()) {
        const canRetry = task.status === "error" || isKilledPendingTask(task) ? "" : "disabled";
        const canCancel = task.status === "pending" ? "" : "disabled";
        const canKill = task.status === "running" ? "" : "disabled";
        const pendingIndex = pendingTasks.findIndex((pendingTask) => pendingTask.id === task.id);
        const canMove = selectedGroup && selectedGroup.execution_state === "draft"
          && task.status === "pending";
        const upDisabled = canMove && pendingIndex > 0 ? "" : "disabled";
        const downDisabled = canMove && pendingIndex < pendingTasks.length - 1 ? "" : "disabled";
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td>${task.id}</td>
          <td>
            <div class="task-actions">
              <span>${index + 1}</span>
              <button data-action="move-up" data-id="${task.id}" ${upDisabled}>Up</button>
              <button data-action="move-down" data-id="${task.id}" ${downDisabled}>Down</button>
            </div>
          </td>
          <td><span class="badge ${task.status}">${task.status}</span></td>
          <td>${taskGpu(task)}</td>
          <td>${taskIdle(task)}</td>
          <td class="command">${task.command}</td>
          <td>${formatTime(task.submitted_at)}</td>
          <td>
            <div class="task-actions">
              <button data-action="logs" data-id="${task.id}">Logs</button>
              <button data-action="retry" data-id="${task.id}" ${canRetry}>Retry</button>
              <button data-action="cancel" data-id="${task.id}" ${canCancel}>Cancel</button>
              <button class="danger" data-action="kill" data-id="${task.id}" ${canKill}>
                Kill
              </button>
            </div>
          </td>
        `;
        tasksBody.appendChild(tr);
      }
      for (const task of historyTasks) {
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td>${task.id}</td>
          <td><span class="badge ${task.status}">${task.status}</span></td>
          <td>${taskGpu(task)}</td>
          <td>${taskIdle(task)}</td>
          <td class="command">${task.command}</td>
          <td>${formatTime(task.finished_at)}</td>
          <td>
            <div class="task-actions">
              <button data-action="logs" data-id="${task.id}">Logs</button>
            </div>
          </td>
        `;
        historyBody.appendChild(tr);
      }
    }

    async function createGroup(event) {
      event.preventDefault();
      const payload = {
        name: document.querySelector("#group-name").value.trim(),
      };
      const description = document.querySelector("#group-description").value.trim();
      if (description) payload.description = description;
      try {
        const group = await api("/groups", {
          method: "POST",
          body: JSON.stringify(payload),
        });
        showNotice(`Group ${group.name} created.`, "ok");
        groupForm.reset();
        await refreshGroups();
      } catch (error) {
        showNotice(error.message, "error");
      }
    }

    async function submitTask(event) {
      event.preventDefault();
      if (!selectedGroup) return;
      const payload = {
        command: document.querySelector("#script-path").value.trim(),
        group_id: selectedGroup.id,
      };
      const cwd = document.querySelector("#cwd").value.trim();
      if (cwd) payload.cwd = cwd;
      const minIdleSeconds = Number(document.querySelector("#min-idle-seconds").value || 120);
      payload.min_idle_seconds = minIdleSeconds;
      try {
        const task = await api("/commands", {
          method: "POST",
          body: JSON.stringify(payload),
        });
        showNotice(`Task ${task.id} submitted to ${selectedGroup.name}.`, "ok");
        submitForm.reset();
        await refreshSelectedGroup();
      } catch (error) {
        showNotice(error.message, "error");
      }
    }

    async function openGroup(groupId) {
      selectedGroup = await api(`/groups/${groupId}`);
      renderDetailHeader(selectedGroup);
      groupsSection.classList.add("hidden");
      detailSection.classList.remove("hidden");
      await refreshSelectedGroup();
    }

    async function deleteGroup(groupId) {
      await api(`/groups/${groupId}`, { method: "DELETE" });
      showNotice(`Group ${groupId} deleted.`, "ok");
      if (selectedGroup && selectedGroup.id === Number(groupId)) {
        selectedGroup = null;
        detailSection.classList.add("hidden");
        groupsSection.classList.remove("hidden");
      }
      await refreshGroups();
    }

    async function startGroup(groupId) {
      await api(`/groups/${groupId}/start`, { method: "POST" });
      showNotice(`Group ${groupId} started.`, "ok");
      await refreshGroups();
      await refreshSelectedGroup();
    }

    async function pauseGroup(groupId) {
      await api(`/groups/${groupId}/pause`, { method: "POST" });
      showNotice(`Group ${groupId} paused.`, "ok");
      await refreshGroups();
      await refreshSelectedGroup();
    }

    async function savePendingOrder(pendingTasks) {
      const pendingIds = pendingTasks.map((task) => task.id);
      await api(`/groups/${selectedGroup.id}/commands/order`, {
        method: "PATCH",
        body: JSON.stringify({ command_ids: pendingIds }),
      });
      await refreshSelectedGroup();
    }

    async function moveTask(taskId, direction) {
      const pendingTasks = currentTasks.filter((task) => task.status === "pending");
      const index = pendingTasks.findIndex((task) => task.id === Number(taskId));
      const nextIndex = index + direction;
      if (index < 0 || nextIndex < 0 || nextIndex >= pendingTasks.length) return;
      const reordered = [...pendingTasks];
      [reordered[index], reordered[nextIndex]] = [reordered[nextIndex], reordered[index]];
      await savePendingOrder(reordered);
      showNotice("Task order updated.", "ok");
    }

    async function groupAction(event) {
      const button = event.target.closest("button[data-action]");
      if (!button || button.disabled) return;
      const id = button.dataset.id;
      try {
        if (button.dataset.action === "open-group") {
          await openGroup(id);
        } else if (button.dataset.action === "delete-group") {
          await deleteGroup(id);
        }
      } catch (error) {
        showNotice(error.message, "error");
      }
    }

    async function taskAction(event) {
      const button = event.target.closest("button[data-action]");
      if (!button || button.disabled) return;
      const id = button.dataset.id;
      const action = button.dataset.action;
      try {
        if (action === "logs") {
          const logs = await api(`/commands/${id}/logs`);
          document.querySelector("#logs-title").textContent = `Task ${id} Logs`;
          document.querySelector("#stdout").textContent = logs.stdout || "";
          document.querySelector("#stderr").textContent = logs.stderr || "";
          logsModal.classList.add("show");
          return;
        }
        if (action === "move-up") {
          await moveTask(id, -1);
          return;
        }
        if (action === "move-down") {
          await moveTask(id, 1);
          return;
        }
        await api(`/commands/${id}/${action}`, { method: "POST" });
        showNotice(`Task ${id} ${action} requested.`, "ok");
        await refreshSelectedGroup();
      } catch (error) {
        showNotice(error.message, "error");
      }
    }

    groupForm.addEventListener("submit", createGroup);
    submitForm.addEventListener("submit", submitTask);
    document.querySelector("#refresh-button").addEventListener("click", async () => {
      await refreshGroups();
      await refreshSelectedGroup();
    });
    document.querySelector("#back-button").addEventListener("click", async () => {
      selectedGroup = null;
      detailSection.classList.add("hidden");
      groupsSection.classList.remove("hidden");
      await refreshGroups();
    });
    document.querySelector("#delete-group-button").addEventListener("click", async () => {
      if (selectedGroup) await deleteGroup(selectedGroup.id);
    });
    document.querySelector("#start-group-button").addEventListener("click", async () => {
      if (selectedGroup) await startGroup(selectedGroup.id);
    });
    document.querySelector("#pause-group-button").addEventListener("click", async () => {
      if (selectedGroup) await pauseGroup(selectedGroup.id);
    });
    groupsBody.addEventListener("click", groupAction);
    tasksBody.addEventListener("click", taskAction);
    document.querySelector("#close-logs").addEventListener("click", () => {
      logsModal.classList.remove("show");
    });

    refreshHealth();
    refreshGroups();
    setInterval(async () => {
      await refreshGroups();
      await refreshSelectedGroup();
    }, 5000);
  </script>
</body>
</html>"""
