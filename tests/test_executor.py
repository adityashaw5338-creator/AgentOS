from datetime import datetime

import pytest
from pydantic import ValidationError

from agent_engine.executor import approve_current_step, execute_next_step, execute_plan
from agent_engine.state import AgentState, AgentStatus, PlanStep
from agent_engine.tools.calculator import add, divide, multiply
from agent_engine.tools.registry import ToolRegistry


def registry_for_calculations():
    registry = ToolRegistry()
    registry.register("add", add)
    registry.register("multiply", multiply)
    registry.register("divide", divide)
    return registry


def make_step(step_id=1, tool_name="add", tool_args=None, **kwargs):
    return PlanStep(
        step_id=step_id,
        description=f"Execute {tool_name}",
        tool_name=tool_name,
        tool_args={"a": 2, "b": 3} if tool_args is None else tool_args,
        **kwargs,
    )


def test_multistep_execution_resolves_typed_results_and_keeps_history():
    state = AgentState(
        goal="Add two and three then multiply by four",
        steps=[
            make_step(),
            make_step(2, "multiply", {"a": {"$ref": 1}, "b": 4}),
        ],
    )
    execute_plan(state, registry_for_calculations())
    assert state.status == AgentStatus.COMPLETED
    assert state.result == "20.0"
    assert state.steps[0].result == 5.0
    assert state.steps[1].result == 20.0
    assert state.current_step == 2
    assert all(step.completed and step.attempts == 1 for step in state.steps)
    assert state.error is None
    assert state.execution_log[-1] == "Task completed successfully."


def test_references_can_nest_in_tool_arguments():
    def collect(values: list[float], labels: dict[str, float]) -> dict:
        return {"total": sum(values), **labels}

    registry = registry_for_calculations()
    registry.register("collect", collect)
    state = AgentState(
        goal="Collect a computed number",
        steps=[
            make_step(),
            make_step(2, "collect", {"values": [{"$ref": 1}, 2], "labels": {"first": {"$ref": 1}}}),
        ],
    )
    execute_plan(state, registry)
    assert state.status == AgentStatus.COMPLETED
    assert state.steps[-1].result == {"total": 7.0, "first": 5.0}


@pytest.mark.parametrize(
    "reference",
    [{"$ref": 2}, {"$ref": 999}, {"$ref": True}, {"$ref": "1"}, {"$ref": 1, "extra": 2}],
)
def test_invalid_reference_never_executes_the_tool(reference):
    state = AgentState(
        goal="Invalid reference", steps=[make_step(tool_args={"a": reference, "b": 2})]
    )
    execute_plan(state, registry_for_calculations())
    assert state.status == AgentStatus.FAILED
    assert state.steps[0].attempts == 0
    assert state.current_step == 0


def test_registry_approval_cannot_be_disabled_by_the_plan():
    calls = []

    def sensitive(a: float, b: float) -> float:
        calls.append((a, b))
        return a + b

    registry = ToolRegistry()
    registry.register("sensitive", sensitive, requires_approval=True)
    state = AgentState(
        goal="Approval test", steps=[make_step(tool_name="sensitive", requires_approval=False)]
    )
    execute_plan(state, registry)
    assert state.status == AgentStatus.WAITING_FOR_APPROVAL
    assert state.steps[0].requires_approval is True
    assert state.steps[0].attempts == 0
    assert calls == []
    approve_current_step(state)
    execute_plan(state, registry)
    assert calls == [(2.0, 3.0)]
    assert state.status == AgentStatus.COMPLETED


def test_approval_resumes_without_repeating_completed_steps():
    state = AgentState(
        goal="Approve second step",
        steps=[
            make_step(),
            make_step(2, "multiply", {"a": {"$ref": 1}, "b": 4}, requires_approval=True),
        ],
    )
    registry = registry_for_calculations()
    execute_plan(state, registry)
    assert state.current_step == 1
    assert state.status == AgentStatus.WAITING_FOR_APPROVAL
    assert state.result == "5.0"
    approve_current_step(state)
    execute_plan(state, registry)
    assert state.result == "20.0"
    assert state.steps[0].attempts == 1
    assert state.steps[1].attempts == 1
    with pytest.raises(ValueError, match="not waiting"):
        approve_current_step(state)


def test_temporary_failures_retry_within_budget():
    attempts = []

    def flaky() -> str:
        attempts.append(1)
        if len(attempts) < 3:
            raise ConnectionError("temporary disconnect")
        return "recovered"

    registry = ToolRegistry()
    registry.register("flaky", flaky)
    state = AgentState(goal="Recover", steps=[make_step(tool_name="flaky", tool_args={})])
    execute_plan(state, registry, max_retries=2)
    assert state.status == AgentStatus.COMPLETED
    assert state.steps[0].attempts == 3
    assert state.result == "recovered"
    assert len(attempts) == 3


def test_retry_exhaustion_fails_and_does_not_run_later_steps():
    attempts = []

    def failing() -> str:
        attempts.append(1)
        raise RuntimeError("unavailable")

    registry = registry_for_calculations()
    registry.register("failing", failing)
    state = AgentState(
        goal="Fail", steps=[make_step(tool_name="failing", tool_args={}), make_step(2)]
    )
    execute_plan(state, registry, max_retries=1)
    assert state.status == AgentStatus.FAILED
    assert len(attempts) == 2
    assert "after 2 attempt(s)" in state.error
    assert state.steps[1].attempts == 0
    assert state.current_step == 0


def test_permanent_tool_failure_is_not_retried():
    state = AgentState(
        goal="Divide by zero", steps=[make_step(tool_name="divide", tool_args={"a": 1, "b": 0})]
    )
    execute_plan(state, registry_for_calculations(), max_retries=5)
    assert state.status == AgentStatus.FAILED
    assert state.steps[0].attempts == 1
    assert "Cannot divide by zero" in state.error


def test_validation_failure_is_detected_before_tool_execution():
    state = AgentState(goal="Invalid arguments", steps=[make_step(tool_args={"a": True, "b": 3})])
    execute_plan(state, registry_for_calculations())
    assert state.status == AgentStatus.FAILED
    assert state.steps[0].attempts == 0


@pytest.mark.parametrize(
    "status",
    [
        AgentStatus.COMPLETED,
        AgentStatus.FAILED,
        AgentStatus.WAITING_FOR_APPROVAL,
        AgentStatus.CANCELLED,
    ],
)
def test_terminal_or_waiting_state_is_not_executed_again(status):
    state = AgentState(goal="No more work", status=status, steps=[make_step()])
    before = state.model_dump()
    execute_plan(state, registry_for_calculations())
    assert state.model_dump() == before


def test_empty_plan_is_a_failure():
    state = AgentState(goal="No plan")
    execute_plan(state, registry_for_calculations())
    assert state.status == AgentStatus.FAILED
    assert state.error == "No plan available."


def test_execution_budget_stops_before_next_tool():
    state = AgentState(goal="Bounded work", steps=[make_step(), make_step(2), make_step(3)])
    execute_plan(state, registry_for_calculations(), max_steps=2)
    assert state.status == AgentStatus.FAILED
    assert state.current_step == 2
    assert state.steps[2].attempts == 0
    assert "Execution limit reached" in state.error


@pytest.mark.parametrize("value", [-1, 0, True, 1.5, 129])
def test_invalid_execution_limits_are_rejected(value):
    with pytest.raises(ValueError, match="max_steps"):
        execute_plan(AgentState(goal="Invalid"), registry_for_calculations(), max_steps=value)


@pytest.mark.parametrize("value", [-1, True, 1.5, 11])
def test_invalid_retry_limits_are_rejected(value):
    with pytest.raises(ValueError, match="max_retries"):
        execute_next_step(
            AgentState(goal="Invalid"), registry_for_calculations(), max_retries=value
        )


@pytest.mark.parametrize(
    "steps,current_step",
    [
        ([make_step(), make_step(1)], 0),
        ([make_step(), make_step(2)], 1),
        ([make_step(completed=True)], 0),
        ([make_step()], 2),
    ],
)
def test_inconsistent_state_is_rejected_without_executing(steps, current_step):
    state = AgentState(goal="Inconsistent", steps=steps, current_step=current_step)
    execute_plan(state, registry_for_calculations())
    assert state.status == AgentStatus.FAILED
    assert all(step.attempts == 0 for step in state.steps)


def test_unknown_or_unassigned_tools_fail_clearly():
    for tool in [None, "missing"]:
        state = AgentState(goal="Missing tool", steps=[make_step(tool_name=tool)])
        execute_plan(state, registry_for_calculations())
        assert state.status == AgentStatus.FAILED
        assert state.steps[0].attempts == 0


def test_task_state_does_not_share_mutable_defaults_and_has_utc_timestamps():
    first, second = AgentState(goal="First"), AgentState(goal="Second")
    first.execution_log.append("Only first")
    assert second.execution_log == []
    assert first.task_id != second.task_id
    assert first.created_at.utcoffset().total_seconds() == 0
    with pytest.raises(ValidationError):
        AgentState(goal="Naive timestamp", created_at=datetime(2026, 1, 1))
    with pytest.raises(ValidationError):
        AgentState(goal="x" * 4001)
    with pytest.raises(ValidationError):
        PlanStep(step_id=0, description="Bad ID")
