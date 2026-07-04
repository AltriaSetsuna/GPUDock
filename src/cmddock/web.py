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

    * {
      box-sizing: border-box;
    }

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
      width: min(1180px, calc(100vw - 32px));
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
      width: min(1180px, calc(100vw - 32px));
      margin: 24px auto 40px;
      display: grid;
      grid-template-columns: minmax(320px, 420px) minmax(0, 1fr);
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

    .panel-body {
      padding: 18px;
    }

    label {
      display: block;
      color: var(--muted);
      font-size: 13px;
      margin-bottom: 7px;
    }

    input, select, textarea {
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

    input:focus, select:focus, textarea:focus {
      border-color: var(--accent);
      box-shadow: 0 0 0 3px rgb(20 108 148 / 16%);
    }

    textarea {
      min-height: 170px;
      resize: vertical;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 12px;
    }

    .field {
      margin-bottom: 14px;
    }

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

    .actions {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
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

    .notice.show {
      display: block;
    }

    .notice.error {
      border-color: #f1b8b2;
      color: var(--danger);
      background: #fff4f2;
    }

    .notice.ok {
      border-color: #acd7c0;
      color: var(--ok);
      background: #f0fbf5;
    }

    .table-wrap {
      overflow-x: auto;
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

    td.command {
      white-space: normal;
      min-width: 260px;
      max-width: 420px;
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
    .badge.succeeded { color: var(--ok); border-color: #acd7c0; background: #f0fbf5; }
    .badge.error { color: var(--danger); border-color: #f1b8b2; background: #fff4f2; }
    .badge.pending { color: var(--warning); border-color: #ead197; background: #fff9e8; }

    .toolbar {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      align-items: center;
    }

    .toolbar select {
      min-width: 130px;
      padding: 7px 9px;
      font-size: 13px;
    }

    .task-actions {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
    }

    .task-actions button {
      padding: 6px 8px;
      font-size: 12px;
    }

    .empty {
      padding: 24px;
      text-align: center;
      color: var(--muted);
      font-size: 14px;
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

    .modal-backdrop.show {
      display: flex;
    }

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

    .modal .panel-body {
      overflow: auto;
    }

    pre {
      margin: 0;
      white-space: pre-wrap;
      word-break: break-word;
      font-size: 12px;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    }

    @media (max-width: 900px) {
      main {
        grid-template-columns: 1fr;
      }

      .row {
        grid-template-columns: 1fr;
      }
    }
  </style>
</head>
<body>
  <header>
    <div class="topbar">
      <div class="brand">
        <h1>GPUDock</h1>
        <div class="subtitle">Submit GPU scripts and watch the scheduler state.</div>
      </div>
      <div id="health" class="status-pill">Checking service...</div>
    </div>
  </header>

  <main>
    <section>
      <div class="section-header">
        <h2>Submit Script</h2>
      </div>
      <div class="panel-body">
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

          <div class="row">
            <div class="field">
              <label for="queue">Queue</label>
              <select id="queue" name="queue">
                <option value="serial">serial</option>
                <option value="parallel">parallel</option>
              </select>
            </div>
            <div class="field">
              <label for="cwd">Working directory</label>
              <input id="cwd" name="cwd" placeholder="optional" />
            </div>
          </div>

          <div class="actions">
            <button class="primary" type="submit">Submit Task</button>
            <button type="button" id="refresh-button">Refresh</button>
          </div>

          <div id="notice" class="notice"></div>
        </form>
      </div>
    </section>

    <section>
      <div class="section-header">
        <h2>Tasks</h2>
        <div class="toolbar">
          <select id="queue-filter">
            <option value="">all queues</option>
            <option value="serial">serial</option>
            <option value="parallel">parallel</option>
          </select>
          <select id="status-filter">
            <option value="">all statuses</option>
            <option value="pending">pending</option>
            <option value="running">running</option>
            <option value="succeeded">succeeded</option>
            <option value="error">error</option>
            <option value="canceled">canceled</option>
          </select>
        </div>
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>ID</th>
              <th>Status</th>
              <th>Queue</th>
              <th>GPU</th>
              <th>Script</th>
              <th>Submitted</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody id="tasks-body"></tbody>
        </table>
        <div id="empty" class="empty">No tasks yet.</div>
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
    const form = document.querySelector("#submit-form");
    const notice = document.querySelector("#notice");
    const body = document.querySelector("#tasks-body");
    const empty = document.querySelector("#empty");
    const health = document.querySelector("#health");
    const queueFilter = document.querySelector("#queue-filter");
    const statusFilter = document.querySelector("#status-filter");
    const logsModal = document.querySelector("#logs-modal");

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
      return "";
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

    async function refreshTasks() {
      const params = new URLSearchParams();
      if (queueFilter.value) params.set("queue", queueFilter.value);
      if (statusFilter.value) params.set("status", statusFilter.value);
      const suffix = params.toString() ? `?${params}` : "";
      const data = await api(`/commands${suffix}`);
      renderTasks(data.commands || []);
    }

    function renderTasks(tasks) {
      body.innerHTML = "";
      empty.style.display = tasks.length ? "none" : "block";
      for (const task of tasks) {
        const canRetry = task.status === "error" ? "" : "disabled";
        const canCancel = task.status === "pending" ? "" : "disabled";
        const canKill = task.status === "running" ? "" : "disabled";
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td>${task.id}</td>
          <td><span class="badge ${task.status}">${task.status}</span></td>
          <td>${task.queue}</td>
          <td>${taskGpu(task)}</td>
          <td class="command">${task.command}</td>
          <td>${formatTime(task.submitted_at)}</td>
          <td>
            <div class="task-actions">
              <button data-action="logs" data-id="${task.id}">Logs</button>
              <button data-action="retry" data-id="${task.id}" ${canRetry}>Retry</button>
              <button data-action="cancel" data-id="${task.id}" ${canCancel}>Cancel</button>
              <button
                class="danger"
                data-action="kill"
                data-id="${task.id}"
                ${canKill}
              >
                Kill
              </button>
            </div>
          </td>
        `;
        body.appendChild(tr);
      }
    }

    async function submitTask(event) {
      event.preventDefault();
      const payload = {
        command: document.querySelector("#script-path").value.trim(),
        queue: document.querySelector("#queue").value,
      };
      const cwd = document.querySelector("#cwd").value.trim();
      if (cwd) payload.cwd = cwd;
      try {
        const task = await api("/commands", {
          method: "POST",
          body: JSON.stringify(payload),
        });
        showNotice(`Task ${task.id} submitted. GPU_COUNT=${task.gpu_count || "pending"}.`, "ok");
        form.reset();
        await refreshTasks();
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
        await api(`/commands/${id}/${action}`, { method: "POST" });
        showNotice(`Task ${id} ${action} requested.`, "ok");
        await refreshTasks();
      } catch (error) {
        showNotice(error.message, "error");
      }
    }

    form.addEventListener("submit", submitTask);
    document.querySelector("#refresh-button").addEventListener("click", refreshTasks);
    document.querySelector("#tasks-body").addEventListener("click", taskAction);
    document.querySelector("#close-logs").addEventListener("click", () => {
      logsModal.classList.remove("show");
    });
    queueFilter.addEventListener("change", refreshTasks);
    statusFilter.addEventListener("change", refreshTasks);

    refreshHealth();
    refreshTasks();
    setInterval(refreshTasks, 5000);
  </script>
</body>
</html>"""
