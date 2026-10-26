import json
from typing import Any

import pytest

from agent_engine.agent import run_agent
from agent_engine.executor import approve_current_step, execute_plan
from agent_engine.state import AgentStatus
from agent_engine.storage.repository import TaskRepository
from agent_engine.tools.registry import ToolRegistry


@pytest.fixture
def repository():
    repository = TaskRepository(database_url="sqlite:///:memory:")
    yield repository
    repository.close()


def test_running_a_goal_persists_the_complete_task(repository):
    state = run_agent("calculate (2 + 3) * 4", repository=repository)
    restored = repository.get_task(state.task_id)
    assert state.status == AgentStatus.COMPLETED
    assert state.result == "20.0"
    assert restored is not None
    assert restored.steps[-1].result == 20.0
    assert restored.model_dump() == state.model_dump()


def test_planning_failure_is_saved_with_a_useful_error(repository):
    state = run_agent("research my profile", repository=repository)
    assert state.status == AgentStatus.FAILED
    assert "arithmetic" in state.error
    assert repository.get_task(state.task_id).error == state.error


def test_tool_failure_is_saved_without_a_false_success(repository):
    state = run_agent("divide 1 by 0", repository=repository)
    assert state.status == AgentStatus.FAILED
    assert "zero" in state.error
    assert state.current_step == 0
    assert state.steps[0].attempts == 1


def test_plan_only_does_not_execute_a_registered_tool(repository):
    calls = []
    registry = ToolRegistry()

    def record(text: str) -> str:
        calls.append(text)
        return text

    registry.register("record", record)
    goal = json.dumps({"steps": [{"tool_name": "record", "tool_args": {"text": "event"}}]})
    state = run_agent(goal, repository=repository, registry=registry, execute=False)
    assert state.status == AgentStatus.PENDING
    assert calls == []
    assert repository.get_task(state.task_id).result is None


def test_approval_policy_applies_to_every_step(repository):
    state = run_agent("(2 + 3) * 4", repository=repository, require_approval=True)
    assert state.status == AgentStatus.WAITING_FOR_APPROVAL
    assert all(step.requires_approval for step in state.steps)
    from agent_engine.agent import build_registry

    approve_current_step(state)
    execute_plan(state, build_registry())
    assert state.current_step == 1
    assert state.status == AgentStatus.WAITING_FOR_APPROVAL
    approve_current_step(state)
    execute_plan(state, build_registry())
    repository.save_task(state)
    assert repository.get_task(state.task_id).result == "20.0"


def test_whitespace_goal_becomes_a_saved_failure(repository):
    state = run_agent("   ", repository=repository)
    assert state.status == AgentStatus.FAILED
    assert "empty" in state.error


@pytest.mark.parametrize("depth", [80, 994])
def test_excessively_nested_goal_is_saved_as_failure(repository, depth):
    registry = ToolRegistry()

    def inspect_payload(payload: Any) -> str:
        return "inspected"

    registry.register("inspect_payload", inspect_payload)
    nested = "[" * depth + "1" + "]" * depth
    goal = '{"steps":[{"tool_name":"inspect_payload","tool_args":{"payload":' + nested + "}}]}"
    assert len(goal) < 4000
    state = run_agent(goal, registry=registry, repository=repository)
    assert state.status == AgentStatus.FAILED
    assert "nested" in state.error or "JSON" in state.error
    assert state.steps == []
    assert repository.get_task(state.task_id).status == AgentStatus.FAILED
