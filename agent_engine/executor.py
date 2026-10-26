"""Execute validated plans with bounded retries and mandatory approval gates."""

from typing import Any

from agent_engine.state import AgentState, AgentStatus, utc_now
from agent_engine.tools.registry import ToolRegistry

TERMINAL_STATUSES = {
    AgentStatus.COMPLETED,
    AgentStatus.FAILED,
    AgentStatus.WAITING_FOR_APPROVAL,
    AgentStatus.CANCELLED,
}


def format_result(result: object) -> str:
    return str(result)


def _fail(state: AgentState, message: str) -> AgentState:
    state.status = AgentStatus.FAILED
    state.error = message
    state.updated_at = utc_now()
    state.execution_log.append(message)
    return state


def _resolve_arguments(value: Any, state: AgentState, depth: int = 0) -> Any:
    if depth > 64:
        raise ValueError("Tool argument nesting exceeds 64 levels.")
    if isinstance(value, dict):
        if "$ref" in value:
            reference = value.get("$ref")
            if len(value) != 1 or isinstance(reference, bool) or not isinstance(reference, int):
                raise ValueError("A result reference must be {'$ref': integer step_id}.")
            matches = [
                step for step in state.steps[: state.current_step] if step.step_id == reference
            ]
            if len(matches) != 1 or not matches[0].completed:
                raise ValueError(f"Reference to step {reference} is not a completed previous step.")
            return matches[0].result
        return {key: _resolve_arguments(item, state, depth + 1) for key, item in value.items()}
    if isinstance(value, list):
        return [_resolve_arguments(item, state, depth + 1) for item in value]
    return value


def execute_next_step(
    state: AgentState,
    registry: ToolRegistry,
    max_retries: int = 2,
) -> AgentState:
    if (
        isinstance(max_retries, bool)
        or not isinstance(max_retries, int)
        or not 0 <= max_retries <= 10
    ):
        raise ValueError("max_retries must be an integer between 0 and 10.")
    if state.status in TERMINAL_STATUSES:
        return state
    if not state.steps:
        return _fail(state, "No plan available.")
    if len({step.step_id for step in state.steps}) != len(state.steps):
        return _fail(state, "Plan contains duplicate step IDs.")
    if state.current_step > len(state.steps):
        return _fail(state, "Current step is outside the plan.")
    if any(not step.completed for step in state.steps[: state.current_step]):
        return _fail(state, "Cannot skip an incomplete step.")
    if state.current_step == len(state.steps):
        state.status = AgentStatus.COMPLETED
        state.updated_at = utc_now()
        return state

    step = state.steps[state.current_step]
    if step.completed:
        return _fail(state, "Current step is already completed; refusing to execute it twice.")
    state.execution_log.append(f"Starting step {step.step_id}: {step.description}")
    if not step.tool_name:
        return _fail(state, f"Step {step.step_id} has no tool assigned.")
    try:
        definition = registry.get(step.tool_name)
        step.requires_approval = step.requires_approval or definition.requires_approval
    except ValueError as error:
        return _fail(state, str(error))

    if step.requires_approval and not step.approved:
        state.status = AgentStatus.WAITING_FOR_APPROVAL
        state.error = None
        state.updated_at = utc_now()
        state.execution_log.append(f"Step {step.step_id} is waiting for human approval.")
        return state

    try:
        arguments = _resolve_arguments(step.tool_args, state)
        registry.validate_arguments(step.tool_name, arguments)
    except ValueError as error:
        return _fail(state, f"Step {step.step_id} failed permanently: {error}")

    state.status = AgentStatus.RUNNING
    last_error: Exception | None = None
    attempts_made = 0
    for attempt in range(max_retries + 1):
        attempts_made = attempt + 1
        step.attempts += 1
        try:
            result = registry.execute(step.tool_name, **arguments)
            step.result = result
            step.completed = True
            state.result = format_result(result)
            state.current_step += 1
            state.error = None
            state.updated_at = utc_now()
            state.execution_log.append(
                f"Step {step.step_id} succeeded using tool '{step.tool_name}' on attempt {attempt + 1}."
            )
            if state.current_step >= len(state.steps):
                state.status = AgentStatus.COMPLETED
                state.execution_log.append("Task completed successfully.")
            else:
                state.status = AgentStatus.PENDING
            return state
        except ValueError as error:
            last_error = error
            state.execution_log.append(
                f"Step {step.step_id} failed permanently: {type(error).__name__}: {error}"
            )
            break
        except Exception as error:
            last_error = error
            state.execution_log.append(
                f"Step {step.step_id}, attempt {attempt + 1} failed: {type(error).__name__}: {error}"
            )

    return _fail(
        state,
        f"Tool '{step.tool_name}' failed after {attempts_made} attempt(s): "
        f"{type(last_error).__name__}: {last_error}",
    )


def execute_plan(
    state: AgentState,
    registry: ToolRegistry,
    max_steps: int = 32,
    max_retries: int = 2,
) -> AgentState:
    if isinstance(max_steps, bool) or not isinstance(max_steps, int) or not 1 <= max_steps <= 128:
        raise ValueError("max_steps must be an integer between 1 and 128.")
    if (
        isinstance(max_retries, bool)
        or not isinstance(max_retries, int)
        or not 0 <= max_retries <= 10
    ):
        raise ValueError("max_retries must be an integer between 0 and 10.")
    if state.status in TERMINAL_STATUSES:
        return state
    if not state.steps or state.current_step >= len(state.steps):
        return execute_next_step(state, registry, max_retries=max_retries)

    steps_executed = 0
    while state.current_step < len(state.steps) and state.status not in TERMINAL_STATUSES:
        if steps_executed >= max_steps:
            return _fail(state, f"Execution limit reached: {max_steps} steps.")
        previous_step = state.current_step
        execute_next_step(state, registry, max_retries=max_retries)
        steps_executed += 1
        if state.current_step == previous_step:
            break
    return state


def approve_current_step(state: AgentState) -> AgentState:
    if state.status != AgentStatus.WAITING_FOR_APPROVAL:
        raise ValueError("Agent is not waiting for approval.")
    if state.current_step >= len(state.steps):
        raise ValueError("No current step to approve.")
    step = state.steps[state.current_step]
    if not step.requires_approval or step.completed:
        raise ValueError("Current step does not require approval.")
    step.approved = True
    state.status = AgentStatus.PENDING
    state.error = None
    state.updated_at = utc_now()
    state.execution_log.append(f"Step {step.step_id} approved by the user.")
    return state
