"use strict";

(() => {
  const $ = (id) => document.getElementById(id);
  const session = { token: "", epoch: 0 };
  const state = { tools: [], tasks: [], total: 0, selected: null, filter: "", search: "", route: "tasks", loadId: 0, detailLoadId: 0, busy: false, scrollTop: 0, mobileComposerOpen: false };
  const statusNames = { planning: "Planning", pending: "Ready", running: "Running", completed: "Completed", failed: "Failed", waiting_for_approval: "Needs approval", cancelled: "Cancelled" };
  const cancellable = new Set(["pending", "planning", "waiting_for_approval"]);
  const pageSize = 25;
  let searchTimer;

  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = String(text);
    return node;
  }

  function statusTag(value) {
    return element("span", `status ${Object.hasOwn(statusNames, value) ? value : ""}`, statusNames[value] || value);
  }

  function announce(id, message, error = false) {
    const target = $(id);
    target.textContent = message;
    target.hidden = !message;
    target.classList.toggle("error", error);
  }

  function detailMessage(message, error = false) {
    const target = $("detail-message");
    if (!target) return;
    target.textContent = message;
    target.hidden = !message;
    target.className = error ? "detail-error" : "form-message";
  }

  function readableDate(value) {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "Date unavailable";
    return date.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
  }

  function jsonValue(value) {
    try { return JSON.stringify(value, null, 2); } catch { return String(value); }
  }

  function errorDetail(body) {
    if (typeof body?.detail === "string") return body.detail;
    if (Array.isArray(body?.detail)) return body.detail.map((item) => item.msg || "Invalid request").join(". ");
    return "The engine could not complete this request.";
  }

  async function api(path, options = {}, token = session.token) {
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), 30000);
    const headers = { Authorization: `Bearer ${token}` };
    if (options.body !== undefined) headers["Content-Type"] = "application/json";
    try {
      const response = await fetch(path, { ...options, headers, body: options.body === undefined ? undefined : JSON.stringify(options.body), signal: controller.signal, cache: "no-store" });
      const body = await response.json().catch((error) => {
        if (error.name === "AbortError") throw error;
        return null;
      });
      if (!response.ok) {
        const message = response.status === 401 ? "That access token was not accepted. Enter the token printed in your terminal." : errorDetail(body);
        throw Object.assign(new Error(message), { status: response.status });
      }
      return body;
    } catch (error) {
      if (typeof error.status === "number") throw error;
      const message = error.name === "AbortError" ? "The engine took too long to respond. Refresh saved tasks before retrying." : "Couldn’t reach the engine. Check that the server is still running, then retry.";
      throw Object.assign(new Error(message), { status: 0 });
    } finally { window.clearTimeout(timer); }
  }

  function active(epoch) { return Boolean(session.token) && session.epoch === epoch; }

  function handleAuth(error) {
    if (error.status === 401 && session.token) disconnect("Your connection token is no longer valid. Enter the server’s current token.");
  }

  async function healthCheck() {
    try {
      const health = await api("/api/health", {}, "");
      $("engine-dot").classList.add("online");
      $("engine-status").textContent = health.version ? `Engine ${health.version}` : "Engine online";
    } catch {
      $("engine-dot").classList.remove("online");
      $("engine-status").textContent = "Engine unavailable";
    }
  }

  function route() {
    state.route = location.hash === "#tools" ? "tools" : "tasks";
    $("tasks-view").hidden = state.route !== "tasks";
    $("tools-view").hidden = state.route !== "tools";
    $("breadcrumb").textContent = state.route === "tools" ? "Tool registry" : "Tasks";
    document.querySelectorAll("[data-route]").forEach((item) => {
      const current = item.dataset.route === state.route;
      item.classList.toggle("active", current);
      if (current) item.setAttribute("aria-current", "page"); else item.removeAttribute("aria-current");
    });
    document.title = `AgentOS · ${state.route === "tools" ? "Tool registry" : "Tasks"}`;
    if (state.route !== "tasks") $("tasks-view").classList.remove("detail-visible");
  }

  function disconnect(message = "") {
    session.token = "";
    session.epoch += 1;
    state.loadId += 1;
    state.detailLoadId += 1;
    window.clearTimeout(searchTimer);
    state.tasks = [];
    state.tools = [];
    state.selected = null;
    state.total = 0;
    state.busy = false;
    $("task-list").replaceChildren();
    $("tool-list").replaceChildren();
    $("task-detail").replaceChildren();
    $("task-list").setAttribute("aria-busy", "false");
    $("load-more").hidden = true;
    $("load-more").disabled = false;
    $("refresh").disabled = false;
    $("tasks-view").classList.remove("detail-visible");
    $("freshness").textContent = "";
    $("task-total").textContent = "Loading…";
    $("list-range").textContent = "";
    $("tool-total").textContent = "";
    $("approval-count").textContent = "";
    announce("composer-message", "");
    announce("list-error", "");
    $("workspace").hidden = true;
    $("connect-view").hidden = false;
    $("disconnect").hidden = true;
    $("mobile-disconnect").hidden = true;
    $("refresh").hidden = true;
    $("connection-label").textContent = "Disconnected";
    $("nav-tool-count").textContent = "";
    $("access-token").value = "";
    $("goal").value = "";
    $("task-search").value = "";
    state.search = "";
    state.filter = "";
    state.mobileComposerOpen = false;
    $("require-approval").checked = false;
    syncFilters();
    announce("connect-error", message, Boolean(message));
    setComposerBusy(false);
    $("access-token").focus();
  }

  async function connect(event) {
    event.preventDefault();
    const candidate = $("access-token").value.trim();
    if (!candidate) return;
    const button = $("connect-button");
    if (button.disabled) return;
    const epoch = session.epoch;
    button.disabled = true;
    button.textContent = "Connecting…";
    announce("connect-error", "");
    try {
      const catalog = await api("/api/tools", {}, candidate);
      if (session.epoch !== epoch) return;
      session.token = candidate;
      session.epoch += 1;
      state.tools = catalog.tools || [];
      $("access-token").value = "";
      $("connect-view").hidden = true;
      $("workspace").hidden = false;
      $("disconnect").hidden = false;
      $("mobile-disconnect").hidden = false;
      $("refresh").hidden = false;
      $("connection-label").textContent = "Connected";
      $("nav-tool-count").textContent = String(state.tools.length);
      renderTools();
      renderDetail();
      route();
      await refresh();
      if (session.token) $("goal").focus();
    } catch (error) { announce("connect-error", error.message, true); }
    finally { button.disabled = false; button.textContent = "Connect workspace"; }
  }

  function renderTools() {
    $("tool-total").textContent = `${state.tools.length} registered ${state.tools.length === 1 ? "tool" : "tools"}`;
    const nodes = state.tools.map((tool) => {
      const item = element("article", "tool-item");
      const heading = element("div", "tool-summary");
      heading.append(element("h2", "", tool.name));
      if (tool.requires_approval) heading.append(statusTag("waiting_for_approval"));
      else heading.append(element("span", "small-text", "Validated arguments"));
      item.append(heading, element("p", "", tool.description || "No description provided."));
      const details = element("details");
      details.append(element("summary", "", "View argument schema"), element("pre", "", jsonValue(tool.parameters || {})));
      item.append(details);
      return item;
    });
    if (!nodes.length) nodes.push(element("p", "empty-state", "No tools are registered in this engine."));
    $("tool-list").replaceChildren(...nodes);
  }

  function renderList() {
    const nodes = state.tasks.map((task) => {
      const row = element("button", "task-row");
      row.type = "button";
      row.dataset.taskId = task.task_id;
      row.classList.toggle("selected", state.selected?.task_id === task.task_id);
      row.setAttribute("aria-pressed", String(state.selected?.task_id === task.task_id));
      row.append(element("span", "task-row-title", task.goal), statusTag(task.status));
      row.append(element("span", "task-row-meta", `${readableDate(task.created_at)} · ${task.steps.length} ${task.steps.length === 1 ? "step" : "steps"}`));
      const result = element("span", "task-row-result", task.result ?? "—");
      if (task.result !== null && task.result !== undefined) result.title = task.result;
      row.append(result);
      row.addEventListener("click", () => selectTask(task.task_id));
      return row;
    });
    if (!nodes.length) {
      const empty = element("div", "empty-state");
      const filtered = Boolean(state.search || state.filter);
      empty.append(element("strong", "", filtered ? "No matching tasks" : "Your first task starts here"));
      empty.append(element("p", "", filtered ? "Try another search or status filter." : "Enter a goal above, or choose an example to see the planner in action."));
      nodes.push(empty);
    }
    $("task-list").replaceChildren(...nodes);
    $("task-total").textContent = `${state.total} ${state.total === 1 ? "task" : "tasks"}${state.search || state.filter ? " in this view" : " saved"}`;
    $("list-range").textContent = state.total ? `${state.tasks.length} of ${state.total} shown` : "";
    $("load-more").hidden = state.tasks.length >= state.total;
    syncMobileComposer();
  }

  function syncMobileComposer() {
    const open = state.mobileComposerOpen || state.total === 0;
    $("task-composer").classList.toggle("mobile-collapsed", !open);
    $("mobile-new-task").setAttribute("aria-expanded", String(open));
    $("mobile-new-task").textContent = open ? "Hide task form" : "New task";
  }

  function actionButton(label, action, primary = false) {
    const button = element("button", `button ${primary ? "primary" : "secondary"}`, label);
    button.type = "button";
    button.dataset.action = action;
    button.disabled = state.busy;
    button.addEventListener("click", () => mutateTask(action));
    return button;
  }

  function renderDetail() {
    const detail = $("task-detail");
    const focusedAction = detail.contains(document.activeElement) ? document.activeElement.dataset.action : null;
    const headingFocused = document.activeElement.id === "detail-heading";
    const task = state.selected;
    if (!task) {
      const blank = element("div", "detail-placeholder");
      blank.append(element("h2", "", "Task details"), element("p", "", "Select a saved task to inspect its tool calls, results, and execution history."));
      blank.firstChild.id = "detail-heading";
      const legend = element("div", "detail-legend");
      ["Goal", "Tool plan", "Result"].forEach((word) => legend.append(element("span", "", word)));
      blank.append(legend);
      detail.replaceChildren(blank);
      return;
    }
    const back = element("button", "text-button mobile-back", "Back to saved tasks");
    back.type = "button";
    back.addEventListener("click", () => {
      $("tasks-view").classList.remove("detail-visible");
      window.scrollTo({ top: state.scrollTop });
      const selectedRow = [...document.querySelectorAll(".task-row")].find((row) => row.dataset.taskId === task.task_id);
      selectedRow?.focus({ preventScroll: true });
    });
    const top = element("div", "detail-topline");
    top.append(element("span", "task-id", `Task ${task.task_id.slice(0, 8)}`), statusTag(task.status));
    const title = element("h2", "detail-title", task.goal);
    title.id = "detail-heading";
    title.tabIndex = -1;
    const meta = element("div", "detail-meta");
    meta.append(element("span", "", `Created ${readableDate(task.created_at)}`), element("span", "", `${task.steps.filter((step) => step.completed).length} of ${task.steps.length} steps complete`));
    const nodes = [back, top, title, meta];
    if (task.result !== null && task.result !== undefined) {
      const result = element("div", "detail-result");
      result.append(element("span", "", task.status === "completed" ? "Final result" : "Latest result"), element("strong", "", task.result));
      nodes.push(result);
    }
    if (task.error) nodes.push(element("p", "detail-error", task.error));
    if (task.status === "waiting_for_approval") nodes.push(element("p", "approval-explanation", "Execution is paused. Review the next tool call, then approve that step or cancel the task."));
    const actions = element("div", "detail-actions");
    if (task.status === "pending") actions.append(actionButton("Execute plan", "execute", true));
    if (task.status === "waiting_for_approval") actions.append(actionButton("Approve next step", "approve", true));
    if (cancellable.has(task.status)) actions.append(actionButton("Cancel task", "cancel"));
    if (actions.childElementCount) nodes.push(actions);
    const message = element("p", "form-message");
    message.id = "detail-message";
    message.setAttribute("role", "status");
    message.hidden = true;
    nodes.push(message);
    const plan = element("section", "detail-section");
    plan.append(element("h3", "", "Tool plan"));
    const steps = element("ol", "step-list");
    task.steps.forEach((step, index) => {
      const item = element("li", `step${step.completed ? " completed" : ""}`);
      item.append(element("span", "step-index", step.step_id));
      const content = element("div");
      const name = element("div", "step-name");
      const waiting = index === task.current_step && task.status === "waiting_for_approval";
      const stepState = step.completed ? "Completed" : waiting ? "Awaiting approval" : task.status === "cancelled" ? "Cancelled" : task.status === "failed" ? (index === task.current_step && step.attempts > 0 ? "Failed" : "Not reached") : step.approved ? "Approved" : step.requires_approval ? "Approval required" : "Ready";
      name.append(element("code", "", step.tool_name || "No tool assigned"), element("span", "step-state", stepState));
      content.append(name, element("p", "step-description", step.description));
      content.append(element("pre", "step-args", JSON.stringify(step.tool_args)));
      if (step.completed) content.append(element("p", "step-output", `Result: ${typeof step.result === "object" ? jsonValue(step.result) : String(step.result)} · ${step.attempts} ${step.attempts === 1 ? "attempt" : "attempts"}`));
      item.append(content);
      steps.append(item);
    });
    if (task.steps.length) plan.append(steps); else plan.append(element("p", "small-text", "No executable plan was created. Review the task error above."));
    nodes.push(plan);
    const log = element("section", "detail-section");
    log.append(element("h3", "", "Execution history"));
    if (task.execution_log.length) {
      const list = element("ul", "log-list");
      task.execution_log.forEach((event) => list.append(element("li", "", event)));
      log.append(list);
    } else log.append(element("p", "small-text", "Execution has not started."));
    nodes.push(log);
    detail.replaceChildren(...nodes);
    if (!state.busy && (focusedAction || headingFocused)) restoreDetailFocus(focusedAction);
  }

  function restoreDetailFocus(action) {
    const target = action ? $("task-detail").querySelector(`[data-action="${action}"]`) : null;
    (target || $("detail-heading"))?.focus({ preventScroll: true });
  }

  function updateSelected(task) {
    if (state.selected?.task_id !== task.task_id || state.selected.revision >= task.revision) return;
    state.selected = task;
    state.tasks = state.tasks.map((item) => item.task_id === task.task_id ? task : item);
    renderDetail();
    renderList();
  }

  async function loadTasks(append = false) {
    const requestId = ++state.loadId;
    const epoch = session.epoch;
    const query = new URLSearchParams({ limit: String(pageSize), offset: String(append ? state.tasks.length : 0) });
    if (state.filter) query.set("status", state.filter);
    if (state.search) query.set("search", state.search);
    $("task-list").setAttribute("aria-busy", "true");
    $("load-more").disabled = true;
    $("list-error").hidden = true;
    try {
      const response = await api(`/api/tasks?${query}`);
      if (!active(epoch) || requestId !== state.loadId) return;
      state.tasks = append ? [...state.tasks, ...response.tasks] : response.tasks;
      state.total = response.total;
      renderList();
      $("freshness").textContent = `Updated ${new Date().toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}`;
    } catch (error) {
      if (!active(epoch) || requestId !== state.loadId) return;
      handleAuth(error);
      if (!active(epoch)) return;
      const notice = $("list-error");
      notice.textContent = error.message;
      const retry = element("button", "text-button", "Retry");
      retry.type = "button";
      retry.addEventListener("click", () => loadTasks(append));
      notice.append(retry);
      notice.hidden = false;
      if (!state.tasks.length) $("task-list").replaceChildren();
    } finally {
      if (requestId === state.loadId) {
        $("task-list").setAttribute("aria-busy", "false");
        $("load-more").disabled = false;
      }
    }
  }

  async function loadStats() {
    const epoch = session.epoch;
    try {
      const stats = await api("/api/stats");
      if (!active(epoch)) return;
      $("approval-count").textContent = stats.waiting_for_approval ? `(${stats.waiting_for_approval})` : "";
    } catch (error) { if (active(epoch)) handleAuth(error); }
  }

  async function refreshSelected() {
    const taskId = state.selected?.task_id;
    const epoch = session.epoch;
    if (!taskId) return;
    const requestId = ++state.detailLoadId;
    try {
      const task = await api(`/api/tasks/${encodeURIComponent(taskId)}`);
      if (!active(epoch) || state.selected?.task_id !== taskId || requestId !== state.detailLoadId) return;
      updateSelected(task);
    } catch (error) {
      if (!active(epoch) || state.selected?.task_id !== taskId || requestId !== state.detailLoadId) return;
      handleAuth(error);
      if (active(epoch)) detailMessage(error.message, true);
    }
  }

  async function refresh() {
    if (!session.token) return;
    const epoch = session.epoch;
    $("refresh").disabled = true;
    await Promise.allSettled([loadTasks(), loadStats(), refreshSelected(), healthCheck()]);
    if (session.epoch === epoch) $("refresh").disabled = false;
  }

  async function selectTask(taskId) {
    if (state.busy) return;
    const epoch = session.epoch;
    const requestId = ++state.detailLoadId;
    state.selected = state.tasks.find((task) => task.task_id === taskId) || null;
    renderList();
    renderDetail();
    if (window.matchMedia("(max-width: 760px)").matches) {
      state.scrollTop = window.scrollY;
      $("tasks-view").classList.add("detail-visible");
      window.scrollTo({ top: 0 });
      $("detail-heading")?.focus({ preventScroll: true });
    }
    try {
      const task = await api(`/api/tasks/${encodeURIComponent(taskId)}`);
      if (!active(epoch) || state.selected?.task_id !== taskId || requestId !== state.detailLoadId) return;
      updateSelected(task);
    } catch (error) {
      if (!active(epoch) || state.selected?.task_id !== taskId || requestId !== state.detailLoadId) return;
      handleAuth(error);
      if (active(epoch)) detailMessage(error.message, true);
    }
  }

  function setComposerBusy(busy, operation = "") {
    $("run-button").disabled = busy;
    $("preview-button").disabled = busy;
    $("goal").disabled = busy;
    $("require-approval").disabled = busy;
    $("run-button").textContent = busy && operation === "run" ? "Running…" : "Run task";
    $("preview-button").textContent = busy && operation === "preview" ? "Planning…" : "Preview plan";
    document.querySelectorAll(".example-button").forEach((button) => { button.disabled = busy; });
    $("task-detail").querySelectorAll(".detail-actions button").forEach((button) => { button.disabled = busy; });
  }

  async function createTask(execute) {
    if (state.busy || !session.token || !$("task-form").reportValidity()) return;
    const epoch = session.epoch;
    const goal = $("goal").value.trim();
    if (!goal) { announce("composer-message", "Enter a task goal before continuing.", true); return; }
    state.busy = true;
    setComposerBusy(true, execute ? "run" : "preview");
    announce("composer-message", "");
    try {
      const task = await api("/api/tasks", { method: "POST", body: { goal, execute, require_approval: $("require-approval").checked } });
      if (!active(epoch)) return;
      state.detailLoadId += 1;
      state.selected = task;
      state.mobileComposerOpen = false;
      state.filter = "";
      state.search = "";
      $("task-search").value = "";
      syncFilters();
      renderDetail();
      await Promise.allSettled([loadTasks(), loadStats()]);
      if (!active(epoch)) return;
      const message = task.status === "failed" ? "Task saved with an error. Review the details before trying another goal." : task.status === "waiting_for_approval" ? "Task saved and paused for your approval." : execute ? "Task completed. Its plan and result are saved below." : "Plan saved. Review the tool calls, then choose Execute plan.";
      announce("composer-message", message, task.status === "failed");
      if (window.matchMedia("(max-width: 760px)").matches) {
        state.scrollTop = window.scrollY;
        $("tasks-view").classList.add("detail-visible");
        window.scrollTo({ top: 0 });
        $("detail-heading")?.focus({ preventScroll: true });
      }
    } catch (error) { if (active(epoch)) { handleAuth(error); announce("composer-message", error.message, true); } }
    finally { if (session.epoch === epoch) { state.busy = false; setComposerBusy(false); } }
  }

  async function mutateTask(action) {
    if (state.busy || !state.selected || !session.token) return;
    const task = state.selected;
    const epoch = session.epoch;
    const focusedAction = $("task-detail").contains(document.activeElement) ? document.activeElement.dataset.action : null;
    state.busy = true;
    setComposerBusy(true);
    const buttons = $("task-detail").querySelectorAll(".detail-actions button");
    buttons.forEach((button) => { button.disabled = true; });
    detailMessage(action === "approve" ? "Approving and continuing execution…" : action === "execute" ? "Executing the plan…" : "Cancelling this task…");
    try {
      const updated = await api(`/api/tasks/${encodeURIComponent(task.task_id)}/${action}`, { method: "POST", body: { revision: task.revision } });
      if (!active(epoch)) return;
      state.detailLoadId += 1;
      state.selected = updated;
      renderDetail();
      await Promise.allSettled([loadTasks(), loadStats()]);
      if (active(epoch)) detailMessage(updated.status === "waiting_for_approval" ? "The next step is waiting for approval." : updated.status === "failed" ? "Execution stopped with an error. Review the history below." : updated.status === "cancelled" ? "Task cancelled. Its history is preserved." : "Execution completed and saved.", updated.status === "failed");
    } catch (error) {
      if (!active(epoch)) return;
      handleAuth(error);
      if (error.status === 409) {
        await refreshSelected();
        if (active(epoch)) detailMessage("The task changed before this action was applied. Its current state is shown; review it before trying again.", true);
      } else detailMessage(error.message, true);
    } finally {
      if (session.epoch === epoch) {
        state.busy = false;
        setComposerBusy(false);
        $("task-detail").querySelectorAll(".detail-actions button").forEach((button) => { button.disabled = false; });
        if (focusedAction && document.activeElement === document.body) restoreDetailFocus(focusedAction);
      }
    }
  }

  function syncFilters() {
    document.querySelectorAll("[data-filter]").forEach((button) => {
      const selected = button.dataset.filter === state.filter;
      button.classList.toggle("selected", selected);
      button.setAttribute("aria-pressed", String(selected));
    });
  }

  $("connect-form").addEventListener("submit", connect);
  $("disconnect").addEventListener("click", () => disconnect());
  $("mobile-disconnect").addEventListener("click", () => disconnect());
  $("refresh").addEventListener("click", refresh);
  $("mobile-new-task").addEventListener("click", () => { state.mobileComposerOpen = $("task-composer").classList.contains("mobile-collapsed"); syncMobileComposer(); if (state.mobileComposerOpen) $("goal").focus(); });
  $("task-form").addEventListener("submit", (event) => { event.preventDefault(); createTask(true); });
  $("preview-button").addEventListener("click", () => createTask(false));
  $("load-more").addEventListener("click", () => loadTasks(true));
  $("goal").addEventListener("keydown", (event) => { if ((event.ctrlKey || event.metaKey) && event.key === "Enter") { event.preventDefault(); createTask(true); } });
  document.querySelectorAll("[data-example]").forEach((button) => button.addEventListener("click", () => { $("goal").value = button.dataset.example; $("goal").focus(); announce("composer-message", ""); }));
  document.querySelectorAll("[data-filter]").forEach((button) => button.addEventListener("click", () => { state.filter = button.dataset.filter; syncFilters(); loadTasks(); }));
  $("task-search").addEventListener("input", () => { window.clearTimeout(searchTimer); searchTimer = window.setTimeout(() => { state.search = $("task-search").value.trim(); loadTasks(); }, 220); });
  window.addEventListener("hashchange", route);
  route();
  healthCheck();
})();
