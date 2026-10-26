import json

import pytest

from agent_engine.agent import build_registry
from agent_engine.executor import execute_plan
from agent_engine.planner import create_plan
from agent_engine.state import AgentState, AgentStatus
from agent_engine.tool_planner import create_tool_plan
from agent_engine.tools.registry import ToolRegistry


@pytest.mark.parametrize(
    ("goal", "expected"),
    [
        ("add 2 and 3", "5.0"),
        ("Please add -2.5 to 3?", "0.5"),
        ("multiply -3 by 4.5", "-13.5"),
        ("subtract 2 from 10", "8.0"),
        ("divide 10 by 2", "5.0"),
        ("raise 2 to the power of 3", "8.0"),
        ("2 to the power 3", "8.0"),
        ("2 plus 3", "5.0"),
        ("7 minus 2", "5.0"),
        ("2 times 3", "6.0"),
        ("9 divided by 3", "3.0"),
        ("calculate (2 + 3) * 4", "20.0"),
        ("2 + 3 * 4", "14.0"),
        ("2 ** 3 ** 2", "512.0"),
        ("-(2 + 3)", "-5.0"),
        ("+(2 + 3)", "5.0"),
        ("42", "42.0"),
        ("add 1e2 and .5", "100.5"),
    ],
)
def test_supported_requests_execute_the_correct_calculation(goal, expected):
    registry = build_registry()
    state = create_tool_plan(AgentState(goal=goal), registry)
    execute_plan(state, registry)
    assert state.status == AgentStatus.COMPLETED
    assert state.result == expected
    assert all(step.completed for step in state.steps)


def test_nested_expression_emits_results_as_references():
    state = create_tool_plan(AgentState(goal="(2 + 3) * (4 - 1)"), build_registry())
    assert [step.tool_name for step in state.steps] == ["add", "subtract", "multiply"]
    assert state.steps[2].tool_args == {"a": {"$ref": 1}, "b": {"$ref": 2}}


@pytest.mark.parametrize(
    "goal",
    [
        "address the report",
        "find my profile",
        "research agent systems",
        "__import__('os').system('echo unsafe')",
        "[1,2,3]",
        "True + 2",
        "1 // 2",
        "2 % 3",
        "x + 1",
        "sqrt(4)",
        "2 ^ 3",
        "",
    ],
)
def test_unsupported_or_unsafe_requests_are_rejected(goal):
    with pytest.raises(ValueError):
        create_tool_plan(AgentState(goal=goal), build_registry())


def test_expression_length_and_number_of_steps_are_bounded():
    with pytest.raises(ValueError, match="limited|complex"):
        create_tool_plan(AgentState(goal=" + ".join(["1"] * 34)), build_registry())


def test_no_nonfinite_literals_are_planned():
    with pytest.raises(ValueError, match="finite"):
        create_tool_plan(AgentState(goal="1e999 + 1"), build_registry())


def test_explicit_custom_tool_plan_preserves_approval_policy():
    registry = ToolRegistry()

    def label(text: str) -> str:
        return text.upper()

    registry.register("label", label, requires_approval=True)
    goal = json.dumps(
        {
            "steps": [
                {"tool_name": "label", "tool_args": {"text": "hello"}, "requires_approval": False}
            ]
        }
    )
    state = create_tool_plan(AgentState(goal=goal), registry)
    assert state.steps[0].requires_approval is True
    execute_plan(state, registry)
    assert state.status == AgentStatus.WAITING_FOR_APPROVAL
    assert state.steps[0].result is None


def test_explicit_multistep_plan_executes_previous_results():
    goal = json.dumps(
        {
            "steps": [
                {"step_id": 10, "tool_name": "add", "tool_args": {"a": 2, "b": 3}},
                {"step_id": 20, "tool_name": "multiply", "tool_args": {"a": {"$ref": 10}, "b": 4}},
            ]
        }
    )
    registry = build_registry()
    state = create_tool_plan(AgentState(goal=goal), registry)
    execute_plan(state, registry)
    assert state.result == "20.0"


@pytest.mark.parametrize(
    "data",
    [
        {"steps": []},
        {"steps": "add"},
        {"steps": [{"tool_name": "missing", "tool_args": {}}]},
        {"steps": [{"tool_name": "add", "tool_args": {"a": 1}}]},
        {"steps": [{"tool_name": "add", "tool_args": {"a": 1, "b": 2, "c": 3}}]},
        {"steps": [{"tool_name": "add", "tool_args": {"a": 1, "b": 2}, "approved": True}]},
        {"steps": [{"tool_name": "add", "tool_args": {"a": {"$ref": 2}, "b": 2}}]},
        {"steps": [{"tool_name": "add", "tool_args": {"a": {"$ref": True}, "b": 2}}]},
        {
            "steps": [
                {"tool_name": "add", "tool_args": {"a": 1, "b": 2}, "requires_approval": "false"}
            ]
        },
        {"steps": [{"tool_name": "add", "tool_args": [], "step_id": 1}]},
        {"steps": [{"tool_name": "add", "tool_args": {"a": 1, "b": 2}, "step_id": True}]},
        {
            "steps": [
                {"tool_name": "add", "tool_args": {"a": 1, "b": 2}},
                {"step_id": 1, "tool_name": "add", "tool_args": {"a": 1, "b": 2}},
            ]
        },
        {"steps": [{"tool_name": "add", "tool_args": {"a": 1, "b": 2}}], "approved": True},
    ],
)
def test_malformed_or_untrusted_explicit_plans_are_rejected(data):
    with pytest.raises(ValueError):
        create_tool_plan(AgentState(goal=json.dumps(data)), build_registry())


def test_partial_reference_validation_rejects_bool_for_other_numeric_argument():
    data = {
        "steps": [
            {"tool_name": "add", "tool_args": {"a": 1, "b": 2}},
            {"tool_name": "multiply", "tool_args": {"a": {"$ref": 1}, "b": True}},
        ]
    }
    with pytest.raises(ValueError):
        create_tool_plan(AgentState(goal=json.dumps(data)), build_registry())


def test_partial_reference_validation_rejects_nonfinite_other_argument():
    goal = '{"steps":[{"tool_name":"add","tool_args":{"a":1,"b":2}},{"tool_name":"multiply","tool_args":{"a":{"$ref":1},"b":1e999}}]}'
    with pytest.raises(ValueError, match="finite"):
        create_tool_plan(AgentState(goal=goal), build_registry())


def test_public_create_plan_produces_executable_calls():
    state = create_plan(AgentState(goal="add 2 and 3"))
    assert state.status == AgentStatus.PENDING
    assert state.steps[0].tool_name == "add"


def test_json_cannot_contain_nan():
    with pytest.raises(ValueError):
        create_tool_plan(
            AgentState(goal='{"steps":[{"tool_name":"add","tool_args":{"a":NaN,"b":1}}]}'),
            build_registry(),
        )
