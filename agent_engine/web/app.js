"use strict";

(() => {
  const $ = (id) => document.getElementById(id);
  const session = { token: "", epoch: 0 };
  const state = { tools: [], tasks: [], total: 0, selected: null, filter: "", search: "", route: "tasks", loadId: 0, detailLoadId: 0, busy: false, scrollTop: 0, mobileComposerOpen: null };
  const planning = { mode: "local", available: false, model: "", message: "", defaultInvalid: false, loaded: false, touched: false, loadId: 0, localApproval: false, timeoutMs: 30000 };
  const statusNames = { planning: "Planning", pending: "Ready", running: "Running", completed: "Completed", failed: "Failed", waiting_for_approval: "Needs approval", cancelled: "Cancelled" };
  const cancellable = new Set(["pending", "planning", "waiting_for_approval"]);
  const pageSize = 25;
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  const motion = { version: 0, submit: null, navigation: null, detail: new Set(), view: new Set() };
  let lastRenderedTask = null;
  let searchTimer;

  function cancelMotion(group) {
    const groups = group ? [motion[group]] : [motion.detail, motion.view];
    groups.forEach((animations) => {
      animations.forEach((animation) => animation.cancel());
      animations.clear();
    });
  }

  function invalidateMotion() {
    motion.version += 1;
    motion.submit = null;
    motion.navigation = null;
    cancelMotion();
  }

  function pointerMotion(event) {
    return event?.isTrusted && event.detail > 0 && !reducedMotion.matches
      ? { version: motion.version, epoch: session.epoch } : null;
  }

  function canAnimate(ticket) {
    return ticket && ticket.version === motion.version && ticket.epoch === session.epoch && !reducedMotion.matches;
  }

  function playMotion(node, keyframes, { duration = 200, delay = 0, id = "agentos-detail" } = {}, group = "detail") {
    if (!node?.animate) return;
    const easing = getComputedStyle(document.documentElement).getPropertyValue("--ease-out").trim() || "cubic-bezier(0.23, 1, 0.32, 1)";
    const animation = node.animate(keyframes, { duration, delay, easing, fill: "backwards" });
    animation.id = id;
    motion[group].add(animation);
    const remove = () => motion[group].delete(animation);
    animation.addEventListener("cancel", remove, { once: true });
    animation.addEventListener("finish", () => { remove(); animation.cancel(); }, { once: true });
  }

  function taskSnapshot(task) {
    return task ? { id: task.task_id, revision: task.revision, result: task.result, current: task.current_step, status: task.status } : null;
  }

  function animateDetail(ticket, previous, task) {
    if (!canAnimate(ticket) || state.route !== "tasks" || !session.token) return;
    const detail = $("task-detail");
    const steps = [...detail.querySelectorAll(".step")];
    if (previous?.id !== task.task_id) {
      playMotion(detail.querySelector(".execution-summary"), [{ opacity: 0.55, transform: "translateY(4px)" }, { opacity: 1, transform: "translateY(0)" }], { id: "agentos-summary-enter" });
      playMotion(detail.querySelector(".detail-result"), [{ opacity: 0.45, transform: "translateY(6px)" }, { opacity: 1, transform: "translateY(0)" }], { id: "agentos-result-enter" });
      steps.forEach((step, index) => playMotion(step, [{ opacity: 0.2, transform: "translateY(8px)" }, { opacity: 1, transform: "translateY(0)" }], { duration: 190, delay: Math.min(index * 35, 70), id: "agentos-step-enter" }));
      return;
    }
    if (task.revision <= previous.revision) return;
    if (task.result !== previous.result) playMotion(detail.querySelector(".detail-result"), [{ opacity: 0.45, transform: "translateY(4px)" }, { opacity: 1, transform: "translateY(0)" }], { duration: 190, id: "agentos-result-update" });
    if (task.current_step !== previous.current || task.status !== previous.status) {
      const current = steps[Math.min(task.current_step, steps.length - 1)];
      playMotion(current, [{ opacity: 0.55, transform: "translateY(4px)" }, { opacity: 1, transform: "translateY(0)" }], { duration: 190, id: "agentos-step-update" });
    }
  }

  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = String(text);
    return node;
  }

  function statusTag(value) {
    return element("span", `status ${Object.hasOwn(statusNames, value) ? value : ""}`, statusNames[value] || value);
  }

  function announce(id, message, error = false, quiet = false) {
    const target = $(id);
    target.textContent = message;
    target.hidden = !message;
    target.classList.toggle("error", error);
    target.classList.toggle("sr-only", Boolean(message) && quiet && !error);
  }

  function detailMessage(message, error = false, quiet = false) {
    const target = $("detail-message");
    if (!target) return;
    target.textContent = message;
    target.hidden = !message;
    target.className = error ? "detail-error" : quiet ? "form-message sr-only" : "form-message";
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
    const { timeoutMs = 30000, ...requestOptions } = options;
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), timeoutMs);
    const headers = { Authorization: `Bearer ${token}` };
    if (options.body !== undefined) headers["Content-Type"] = "application/json";
    try {
      const response = await fetch(path, { ...requestOptions, headers, body: options.body === undefined ? undefined : JSON.stringify(options.body), signal: controller.signal, cache: "no-store" });
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

  function renderPlanner() {
    const ai = planning.mode === "openai";
    $("planner").value = planning.mode;
    $("planner").disabled = state.busy;
    $("planner-openai").disabled = !planning.available;
    $("planner-openai").textContent = planning.available && planning.model ? `AI · ${planning.model}` : "AI";
    $("require-approval").checked = ai || planning.localApproval;
    $("require-approval").disabled = state.busy || ai;
    $("composer-scope").textContent = ai ? "A goal for your registered tools" : "Arithmetic or a structured plan";
    let hint = "";
    if (session.token) {
      if (!planning.loaded) hint = "Checking AI availability. Local planning is ready.";
      else if (ai) hint = "Your goal and tool schemas are sent to the configured AI provider. Every step needs your approval.";
      else if (planning.defaultInvalid) hint = "Local is selected for this task.";
      else if (planning.available) hint = "AI can turn natural-language goals into plans for your registered tools.";
      else hint = planning.message || "AI is not configured. Set up an AI provider on the server to enable it.";
      if (planning.loaded && planning.defaultInvalid) hint = `${planning.message || "The server’s default planner is invalid."} ${hint}`;
    }
    $("planner-hint").textContent = hint;
    $("planner-hint").hidden = !hint;
  }

  function resetPlanner() {
    planning.loadId += 1;
    planning.mode = "local";
    planning.available = false;
    planning.model = "";
    planning.message = "";
    planning.defaultInvalid = false;
    planning.loaded = false;
    planning.touched = false;
    planning.localApproval = false;
    planning.timeoutMs = 30000;
    $("planner").setAttribute("aria-busy", "false");
    renderPlanner();
  }

  async function loadPlanner() {
    const epoch = session.epoch;
    const requestId = ++planning.loadId;
    $("planner").setAttribute("aria-busy", "true");
    try {
      const metadata = await api("/api/planner");
      if (!active(epoch) || requestId !== planning.loadId) return;
      if (!metadata || typeof metadata.openai_available !== "boolean" || !["local", "openai", null].includes(metadata.default)) throw new Error("Invalid planner configuration.");
      planning.available = metadata.openai_available;
      planning.model = typeof metadata.model === "string" ? metadata.model : "";
      planning.message = typeof metadata.message === "string" ? metadata.message : "";
      planning.defaultInvalid = metadata.default === null;
      planning.timeoutMs = typeof metadata.timeout_seconds === "number" && Number.isFinite(metadata.timeout_seconds) ? Math.max(30000, Math.min(120, metadata.timeout_seconds) * 3000 + 5000) : 30000;
      planning.loaded = true;
      if (!planning.available) planning.mode = "local";
      else if (!planning.touched) planning.mode = metadata.default || "local";
      renderPlanner();
    } catch (error) {
      if (!active(epoch) || requestId !== planning.loadId) return;
      handleAuth(error);
      if (!active(epoch)) return;
      planning.mode = "local";
      planning.available = false;
      planning.model = "";
      planning.defaultInvalid = false;
      planning.timeoutMs = 30000;
      planning.message = "AI availability could not be checked. Local is selected; refresh to try again.";
      planning.loaded = true;
      renderPlanner();
    } finally {
      if (active(epoch) && requestId === planning.loadId) $("planner").setAttribute("aria-busy", "false");
    }
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
    const previous = state.route;
    const intent = motion.navigation;
    motion.navigation = null;
    cancelMotion("view");
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
    if (previous !== state.route) {
      cancelMotion("detail");
      if (intent?.route === state.route && canAnimate(intent.ticket) && session.token) {
        playMotion($(state.route === "tools" ? "tools-view" : "tasks-view"), [{ opacity: 0.7, transform: "translateY(4px)" }, { opacity: 1, transform: "translateY(0)" }], { id: "agentos-view-enter" }, "view");
      }
    }
  }

  function disconnect(message = "") {
    invalidateMotion();
    lastRenderedTask = null;
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
    $("registered-tools").replaceChildren();
    $("task-detail").replaceChildren();
    $("task-list").setAttribute("aria-busy", "false");
    $("list-loading").hidden = true;
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
    state.mobileComposerOpen = null;
    resetPlanner();
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
      resetPlanner();
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
    $("registered-tools").replaceChildren(...state.tools.map((tool) => element("code", "", tool.name)));
    if (!state.tools.length) $("registered-tools").textContent = "None registered";
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
      row.addEventListener("click", (event) => selectTask(task.task_id, pointerMotion(event)));
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
    const open = state.mobileComposerOpen ?? state.total === 0;
    $("task-composer").classList.toggle("mobile-collapsed", !open);
    $("mobile-new-task").setAttribute("aria-expanded", String(open));
    $("mobile-new-task").textContent = open ? "Hide task form" : "New task";
  }

  function actionButton(label, action, primary = false) {
    const button = element("button", `button ${primary ? "primary" : "secondary"}`, label);
    button.type = "button";
    button.dataset.action = action;
    button.disabled = state.busy;
    button.addEventListener("click", (event) => mutateTask(action, pointerMotion(event)));
    return button;
  }

  function editGoal(task, local = false) {
    if (state.busy || !session.token) return;
    const draft = $("goal").value.trim();
    const conflict = draft && draft !== task.goal.trim();
    if (!conflict) {
      $("goal").value = task.goal;
      if (local) {
        planning.mode = "local";
        planning.touched = true;
        renderPlanner();
      }
    }
    state.mobileComposerOpen = true;
    $("tasks-view").classList.remove("detail-visible");
    syncMobileComposer();
    announce("composer-message", conflict
      ? "Your current draft is kept. Clear it before choosing Edit goal on this saved task."
      : local ? "Local planner selected. Review this goal, then preview or run it."
      : "Edit this goal, then preview or run a new task. The saved history is kept.");
    $("goal").focus();
  }

  function renderDetail(ticket = null) {
    const detail = $("task-detail");
    const previous = lastRenderedTask;
    cancelMotion("detail");
    const focusedAction = detail.contains(document.activeElement) ? document.activeElement.dataset.action : null;
    const headingFocused = document.activeElement.id === "detail-heading";
    const task = state.selected;
    lastRenderedTask = taskSnapshot(task);
    if (!task) {
      const blank = element("div", "detail-placeholder");
      blank.append(element("h2", "", "Task details"), element("p", "", "Select a saved task to inspect its tool calls, results, and execution history."));
      blank.firstChild.id = "detail-heading";
      const guide = element("ol", "workflow-guide");
      guide.setAttribute("aria-label", "How a task runs");
      [
        ["Plan goal", "Turn the request into an ordered tool plan."],
        ["Validate tools", "Check arguments against each registered tool."],
        ["Review approval", "Approve any step that needs your decision."],
        ["Execute", "Run the steps and inspect their saved results."],
      ].forEach(([label, description], index) => {
        const item = element("li");
        const number = element("span", "workflow-guide-index", String(index + 1));
        number.setAttribute("aria-hidden", "true");
        const content = element("div", "workflow-guide-content");
        content.append(element("strong", "", label), element("p", "", description));
        item.append(number, content);
        guide.append(item);
      });
      blank.append(element("h3", "workflow-guide-heading", "How a task runs"), guide);
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
    meta.append(element("span", "", `Created ${readableDate(task.created_at)}`));
    const completed = task.steps.filter((step) => step.completed).length;
    const current = task.steps[task.current_step];
    const summaryText = task.status === "waiting_for_approval" ? `Step ${current?.step_id ?? task.current_step + 1} needs approval`
      : task.status === "completed" ? "All steps completed"
      : task.status === "pending" ? "Ready to execute"
      : task.status === "planning" ? "Building the tool plan"
      : task.status === "running" ? current ? `Running step ${current.step_id}` : "Execution in progress"
      : task.status === "failed" ? task.steps.length ? "Execution stopped" : "Planning stopped"
      : task.status === "cancelled" ? "Task cancelled" : statusNames[task.status] || task.status;
    const summary = element("div", "execution-summary");
    summary.dataset.status = task.status;
    const summaryCopy = element("div", "execution-summary-copy");
    summaryCopy.append(element("span", "execution-label", "Execution"), element("p", "execution-state", summaryText));
    const progressText = task.steps.length ? `${completed} of ${task.steps.length} complete` : "No tool steps";
    const progress = element("progress", "plan-progress");
    progress.max = Math.max(1, task.steps.length);
    progress.value = completed;
    progress.hidden = task.steps.length === 0;
    progress.setAttribute("aria-label", "Tool steps completed");
    progress.setAttribute("aria-valuetext", progressText);
    summary.append(summaryCopy, element("span", "plan-progress-meta", progressText), progress);
    const nodes = [back, top, title, meta, summary];
    if (task.result !== null && task.result !== undefined) {
      const result = element("div", "detail-result");
      result.append(element("span", "", task.status === "completed" ? "Final result" : "Latest result"), element("strong", "", task.result));
      nodes.push(result);
    }
    if (task.error) nodes.push(element("p", "detail-error", task.error));
    if (task.status === "failed" && !task.steps.length) nodes.push(element("p", "recovery-hint", "Planning stopped before any tool ran. Edit the goal or use Local for arithmetic and explicit JSON plans."));
    if (task.status === "waiting_for_approval") {
      const approval = element("div", "approval-explanation");
      approval.append(element("p", "", "Execution is paused. Review the next tool call, then approve that step or cancel the task."));
      if (current) {
        const call = element("div", "approval-call");
        call.append(element("span", "approval-call-label", "Next tool"), element("code", "approval-tool", current.tool_name || "No tool assigned"), element("pre", "approval-args", JSON.stringify(current.tool_args)));
        approval.append(call);
      }
      nodes.push(approval);
    }
    const actions = element("div", "detail-actions");
    if (task.status === "pending") actions.append(actionButton("Execute plan", "execute", true));
    if (task.status === "waiting_for_approval") actions.append(actionButton("Approve next step", "approve", true));
    if (cancellable.has(task.status)) actions.append(actionButton("Cancel task", "cancel"));
    if (task.status === "failed") {
      const edit = element("button", "button secondary", "Edit goal");
      edit.type = "button";
      edit.dataset.action = "edit";
      edit.disabled = state.busy;
      edit.addEventListener("click", () => editGoal(task));
      actions.append(edit);
      if (!task.steps.length) {
        const local = element("button", "button secondary", "Edit with Local");
        local.type = "button";
        local.dataset.action = "edit-local";
        local.disabled = state.busy;
        local.addEventListener("click", () => editGoal(task, true));
        actions.append(local);
      }
    }
    if (actions.childElementCount) nodes.push(actions);
    const message = element("p", "form-message");
    message.id = "detail-message";
    message.setAttribute("role", "status");
    message.hidden = true;
    nodes.push(message);
    const plan = element("section", "detail-section");
    const planHeading = element("div", "detail-section-heading");
    planHeading.append(element("h3", "", "Tool plan"), element("span", "step-count", `${task.steps.length} ${task.steps.length === 1 ? "step" : "steps"}`));
    plan.append(planHeading);
    const steps = element("ol", "step-list");
    task.steps.forEach((step, index) => {
      const item = element("li", `step${step.completed ? " completed" : ""}`);
      item.dataset.stepId = String(step.step_id);
      item.append(element("span", "step-index", step.step_id));
      const content = element("div", "step-content");
      const name = element("div", "step-name");
      const waiting = index === task.current_step && task.status === "waiting_for_approval";
      item.classList.toggle("waiting", waiting);
      if (waiting) item.setAttribute("aria-current", "step");
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
    animateDetail(ticket, previous, task);
  }

  function restoreDetailFocus(action) {
    const target = action ? $("task-detail").querySelector(`[data-action="${action}"]`) : null;
    (target || $("detail-heading"))?.focus({ preventScroll: true });
  }

  function updateSelected(task) {
    if (state.selected?.task_id !== task.task_id || state.selected.revision >= task.revision) return;
    announce("composer-message", "");
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
    $("list-loading").hidden = false;
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
        $("list-loading").hidden = true;
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
    cancelMotion();
    const epoch = session.epoch;
    $("refresh").disabled = true;
    // Planner setup is optional; a slow metadata response must not hold the local
    // workspace or a later connection open. loadPlanner guards its own session.
    loadPlanner();
    await Promise.allSettled([loadTasks(), loadStats(), refreshSelected(), healthCheck()]);
    if (session.epoch === epoch) $("refresh").disabled = false;
  }

  async function selectTask(taskId, ticket = null) {
    if (state.busy) return;
    if (state.selected?.task_id !== taskId) announce("composer-message", "");
    const epoch = session.epoch;
    const requestId = ++state.detailLoadId;
    state.selected = state.tasks.find((task) => task.task_id === taskId) || null;
    renderList();
    if (window.matchMedia("(max-width: 760px)").matches) {
      state.scrollTop = window.scrollY;
      $("tasks-view").classList.add("detail-visible");
      window.scrollTo({ top: 0 });
    }
    renderDetail(ticket);
    if (window.matchMedia("(max-width: 760px)").matches) $("detail-heading")?.focus({ preventScroll: true });
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
    $("task-form").setAttribute("aria-busy", String(busy));
    renderPlanner();
    $("run-button").textContent = busy && operation === "run" ? planning.mode === "openai" ? "Planning…" : "Running…" : "Run task";
    $("preview-button").textContent = busy && operation === "preview" ? "Planning…" : "Preview plan";
    document.querySelectorAll(".example-button").forEach((button) => { button.disabled = busy; });
    $("task-detail").querySelectorAll(".detail-actions button").forEach((button) => { button.disabled = busy; });
    const creating = busy && Boolean(operation);
    $("composer-progress").hidden = !creating;
    $("progress-label").textContent = !creating ? "" : planning.mode === "openai" ? "Requesting an AI plan…" : operation === "preview" ? "Validating the tool plan…" : "Running your task…";
    $("progress-hint").textContent = !creating ? "" : planning.mode === "openai" ? "Waiting for the provider. Every proposed step will need your approval." : "The engine is saving the plan and its execution state.";
  }

  async function createTask(execute, ticket = null) {
    if (state.busy || !session.token || !$("task-form").reportValidity()) return;
    const epoch = session.epoch;
    const goal = $("goal").value.trim();
    if (!goal) { announce("composer-message", "Enter a task goal before continuing.", true); return; }
    const planner = planning.mode;
    const requireApproval = planner === "openai" || $("require-approval").checked;
    const timeoutMs = planner === "openai" ? planning.timeoutMs : 30000;
    planning.touched = true;
    state.busy = true;
    setComposerBusy(true, execute ? "run" : "preview");
    announce("composer-message", "");
    try {
      const task = await api("/api/tasks", { method: "POST", timeoutMs, body: { goal, execute, require_approval: requireApproval, planner } });
      if (!active(epoch)) return;
      state.detailLoadId += 1;
      state.selected = task;
      state.mobileComposerOpen = false;
      state.filter = "";
      state.search = "";
      $("task-search").value = "";
      syncFilters();
      if (window.matchMedia("(max-width: 760px)").matches) {
        state.scrollTop = window.scrollY;
        $("tasks-view").classList.add("detail-visible");
        window.scrollTo({ top: 0 });
      }
      renderDetail(ticket);
      if (window.matchMedia("(max-width: 760px)").matches) $("detail-heading")?.focus({ preventScroll: true });
      await Promise.allSettled([loadTasks(), loadStats()]);
      if (!active(epoch)) return;
      const message = task.status === "failed" ? task.error || "Task saved with an error. Review the details and choose Edit goal." : task.status === "waiting_for_approval" ? "Task saved and paused for your approval." : execute ? "Task completed. Its plan and result are saved below." : "Plan saved. Review the tool calls, then choose Execute plan.";
      announce("composer-message", message, task.status === "failed", task.status !== "failed");
    } catch (error) { if (active(epoch)) { handleAuth(error); announce("composer-message", error.message, true); } }
    finally { if (session.epoch === epoch) { state.busy = false; setComposerBusy(false); } }
  }

  async function mutateTask(action, ticket = null) {
    if (state.busy || !state.selected || !session.token) return;
    announce("composer-message", "");
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
      renderDetail(ticket);
      await Promise.allSettled([loadTasks(), loadStats()]);
      if (active(epoch)) detailMessage(updated.status === "waiting_for_approval" ? "The next step is waiting for approval." : updated.status === "failed" ? "Execution stopped with an error. Review the history below." : updated.status === "cancelled" ? "Task cancelled. Its history is preserved." : "Execution completed and saved.", updated.status === "failed", updated.status !== "failed");
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

  // Pointer press feedback never delays an action or animates keyboard navigation.
  let pressed;
  const clearPress = () => { pressed?.classList.remove("is-pressed"); pressed = null; };
  document.addEventListener("pointerdown", (event) => {
    clearPress();
    if (event.button !== 0 || !event.isPrimary) return;
    pressed = event.target.closest(".button:enabled, .icon-button:enabled");
    pressed?.classList.add("is-pressed");
  });
  document.addEventListener("pointerup", clearPress);
  document.addEventListener("pointercancel", clearPress);
  document.addEventListener("keydown", clearPress);
  window.addEventListener("blur", clearPress);

  // Capture the initiating click before async work. Keyboard input cancels active
  // effects and invalidates pending pointer effects, so it always stays immediate.
  document.addEventListener("keydown", invalidateMotion, true);
  reducedMotion.addEventListener("change", invalidateMotion);
  document.addEventListener("click", (event) => {
    if (event.target.closest("#run-button")) {
      const ticket = pointerMotion(event);
      motion.submit = ticket;
      // The browser's default submit follows click dispatch. Expire an unused
      // ticket next task (invalid forms never submit), after that default action.
      window.setTimeout(() => { if (motion.submit === ticket) motion.submit = null; }, 0);
    }
    const link = event.target.closest('a[href="#tasks"], a[href="#tools"]');
    if (link) motion.navigation = { route: link.hash === "#tools" ? "tools" : "tasks", ticket: pointerMotion(event) };
  }, true);

  $("connect-form").addEventListener("submit", connect);
  $("disconnect").addEventListener("click", () => disconnect());
  $("mobile-disconnect").addEventListener("click", () => disconnect());
  $("refresh").addEventListener("click", refresh);
  $("mobile-new-task").addEventListener("click", () => { state.mobileComposerOpen = $("task-composer").classList.contains("mobile-collapsed"); syncMobileComposer(); if (state.mobileComposerOpen) $("goal").focus(); });
  $("task-form").addEventListener("submit", (event) => { event.preventDefault(); const ticket = motion.submit; motion.submit = null; createTask(true, ticket); });
  $("preview-button").addEventListener("click", (event) => createTask(false, pointerMotion(event)));
  $("planner").addEventListener("change", () => {
    planning.mode = $("planner").value === "openai" && planning.available ? "openai" : "local";
    planning.touched = true;
    renderPlanner();
  });
  $("require-approval").addEventListener("change", () => { if (planning.mode === "local") planning.localApproval = $("require-approval").checked; });
  $("load-more").addEventListener("click", () => loadTasks(true));
  $("goal").addEventListener("keydown", (event) => { if ((event.ctrlKey || event.metaKey) && event.key === "Enter") { event.preventDefault(); createTask(true); } });
  document.querySelectorAll("[data-example]").forEach((button) => button.addEventListener("click", () => { $("goal").value = button.dataset.example; $("goal").focus(); announce("composer-message", ""); }));
  document.querySelectorAll("[data-filter]").forEach((button) => button.addEventListener("click", () => { state.filter = button.dataset.filter; syncFilters(); loadTasks(); }));
  $("task-search").addEventListener("input", () => { window.clearTimeout(searchTimer); searchTimer = window.setTimeout(() => { state.search = $("task-search").value.trim(); loadTasks(); }, 220); });
  window.addEventListener("hashchange", route);
  route();
  healthCheck();
})();
