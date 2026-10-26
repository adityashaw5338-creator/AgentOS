import json
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict

from agent_engine.tools.calculator import add, divide, multiply, power, subtract
from agent_engine.tools.registry import ToolRegistry


class WorkflowPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    values: list[int]


def test_typed_model_arguments_reach_the_callable_as_models():
    seen = []

    def total(payload: WorkflowPayload) -> int:
        seen.append(payload)
        return sum(payload.values)

    registry = ToolRegistry()
    registry.register("total", total)
    assert registry.validate_arguments("total", {"payload": {"values": [2, 3]}}) == {
        "payload": {"values": [2, 3]}
    }
    assert registry.execute("total", payload={"values": [2, 3]}) == 5
    assert isinstance(seen[0], WorkflowPayload)


@pytest.mark.parametrize("reference", [False, True])
def test_typed_model_arguments_survive_saved_approval_resume(reference):
    from agent_engine.agent import run_agent
    from agent_engine.executor import approve_current_step, execute_plan
    from agent_engine.storage.repository import TaskRepository

    def produce() -> dict:
        return {"values": [2, 3]}

    def total(payload: WorkflowPayload) -> int:
        return sum(payload.values)

    registry = ToolRegistry()
    registry.register("produce", produce)
    registry.register("total", total, requires_approval=True)
    steps = [{"tool_name": "produce"}] if reference else []
    steps.append(
        {
            "tool_name": "total",
            "tool_args": {"payload": {"$ref": 1} if reference else {"values": [2, 3]}},
        }
    )
    repository = TaskRepository("sqlite:///:memory:")
    try:
        state = run_agent(json.dumps({"steps": steps}), registry=registry, repository=repository)
        assert state.status.value == "waiting_for_approval"
        saved = repository.get_task(state.task_id)
        approve_current_step(saved)
        execute_plan(saved, registry)
        repository.save_task(saved)
        assert saved.status.value == "completed"
        assert saved.result == "5"
        assert saved.steps[-1].attempts == 1
        assert repository.get_task(saved.task_id).model_dump() == saved.model_dump()
    finally:
        repository.close()


def test_registered_schema_matches_callable_and_defaults():
    def greet(name: str, *, punctuation: str = "!") -> str:
        """Greet a person."""
        return f"Hello {name}{punctuation}"

    registry = ToolRegistry()
    registry.register("greet", greet)
    schema = registry.get_schemas()["greet"]
    assert schema["required"] == ["name"]
    assert schema["properties"]["punctuation"]["default"] == "!"
    assert schema["additionalProperties"] is False
    assert registry.execute("greet", name="Ada") == "Hello Ada!"
    assert registry.validate_arguments("greet", {"name": "Ada"}) == {
        "name": "Ada",
        "punctuation": "!",
    }
    assert registry.list_tools()[0]["description"] == "Greet a person."
    json.dumps(registry.list_tools())


@pytest.mark.parametrize(
    "arguments",
    [
        {"a": 1},
        {"a": 1, "b": 2, "extra": 3},
        {"a": True, "b": 2},
        {"a": "1", "b": 2},
        {"a": float("nan"), "b": 2},
        {"a": float("inf"), "b": 2},
        {"a": None, "b": 2},
    ],
)
def test_invalid_arguments_do_not_call_the_tool(arguments):
    calls = []

    def record(a: float, b: float) -> float:
        calls.append((a, b))
        return a + b

    registry = ToolRegistry()
    registry.register("record", record)
    with pytest.raises(ValueError, match="Invalid arguments"):
        registry.execute("record", **arguments)
    assert calls == []


def test_float_arguments_accept_integers_and_return_normalized_arguments():
    registry = ToolRegistry()
    registry.register("add", add)
    assert registry.validate_arguments("add", {"a": 2, "b": 3}) == {"a": 2.0, "b": 3.0}
    assert registry.execute("add", a=2, b=3) == 5.0


def test_unknown_and_duplicate_tools_are_rejected():
    registry = ToolRegistry()
    registry.register("add", add)
    with pytest.raises(ValueError, match="already registered"):
        registry.register("add", subtract)
    with pytest.raises(ValueError, match="Unknown tool"):
        registry.execute("shell", command="whoami")
    assert registry.execute("add", a=1, b=2) == 3


@pytest.mark.parametrize("name", ["", "UPPER", "a-b", "../escape", "tool name", "a" * 65])
def test_tool_names_are_bounded_identifiers(name):
    with pytest.raises(ValueError, match="Tool names"):
        ToolRegistry().register(name, add)


def test_unsupported_signatures_are_rejected():
    def no_annotations(a):
        return a

    def positional_only(a: int, /) -> int:
        return a

    def variadic(*a: int) -> int:
        return sum(a)

    async def asynchronous(a: int) -> int:
        return a

    for function in [no_annotations, positional_only, variadic, asynchronous]:
        with pytest.raises(ValueError):
            ToolRegistry().register("invalid", function)


def test_registry_exposes_immutable_approval_policy():
    registry = ToolRegistry()
    definition = registry.register(
        "add", add, "An approval-gated calculation.", requires_approval=True
    )
    assert definition.requires_approval
    assert registry.list_tools()[0]["requires_approval"] is True
    with pytest.raises(AttributeError):
        definition.requires_approval = False


def test_nonfinite_and_unserializable_results_are_permanent_errors():
    def nonfinite() -> float:
        return float("inf")

    def object_result() -> object:
        return object()

    registry = ToolRegistry()
    registry.register("nonfinite", nonfinite)
    registry.register("object_result", object_result)
    for name in ["nonfinite", "object_result"]:
        with pytest.raises(ValueError, match="non-JSON or non-finite result"):
            registry.execute(name)


@pytest.mark.parametrize("number", [float("inf"), float("-inf"), float("nan")])
def test_nonfinite_numbers_in_any_containers_never_reach_tools(number):
    seen = []

    def inspect_data(data: dict[str, Any]) -> str:
        seen.append(data)
        return "received"

    registry = ToolRegistry()
    registry.register("inspect_data", inspect_data)
    with pytest.raises(ValueError, match="finite real numbers"):
        registry.execute("inspect_data", data={"nested": [number]})
    assert seen == []


def test_nonfinite_defaults_cannot_publish_invalid_tool_schemas():
    seen = []

    def inspect_default(data: Any = float("inf")) -> str:
        seen.append(data)
        return "received"

    registry = ToolRegistry()
    with pytest.raises(ValueError, match="invalid default"):
        registry.register("inspect_default", inspect_default)
    assert registry.list_tools() == []
    assert seen == []


def test_deep_defaults_are_rejected_before_publishing_tool_schema():
    deeply_nested = 1
    for _ in range(65):
        deeply_nested = [deeply_nested]

    def inspect_default(data: Any = deeply_nested) -> str:
        return "received"

    registry = ToolRegistry()
    with pytest.raises(ValueError, match="nesting exceeds 64"):
        registry.register("inspect_default", inspect_default)
    assert registry.list_tools() == []


def test_excessive_container_depth_is_a_permanent_validation_error():
    seen = []

    def inspect_data(data: Any) -> str:
        seen.append(data)
        return "received"

    registry = ToolRegistry()
    registry.register("inspect_data", inspect_data)
    deeply_nested = 1
    for _ in range(65):
        deeply_nested = [deeply_nested]
    with pytest.raises(ValueError, match="nesting exceeds 64"):
        registry.execute("inspect_data", data=deeply_nested)
    assert seen == []


def test_json_exponent_overflow_is_failed_without_persisting_corrupt_arguments():
    from agent_engine.agent import run_agent
    from agent_engine.storage.repository import TaskRepository

    seen = []

    def inspect_data(data: dict[str, Any]) -> str:
        seen.append(data)
        return "received"

    registry = ToolRegistry()
    registry.register("inspect_data", inspect_data)
    repository = TaskRepository("sqlite:///:memory:")
    try:
        state = run_agent(
            '{"steps":[{"tool_name":"inspect_data","tool_args":{"data":{"value":1e999}}}]}',
            registry=registry,
            repository=repository,
        )
        stored = repository.get_task(state.task_id)
        assert state.status.value == "failed"
        assert "finite real numbers" in state.error
        assert stored.model_dump() == state.model_dump()
        assert stored.steps == []
        assert seen == []
    finally:
        repository.close()


def test_json_results_keep_reference_types_across_saved_approval_resume():
    from agent_engine.agent import run_agent
    from agent_engine.executor import approve_current_step, execute_plan
    from agent_engine.storage.repository import TaskRepository

    def produce() -> dict:
        return {1: (2, 3)}

    def consume(data: dict[str, list[int]]) -> int:
        return sum(data["1"])

    registry = ToolRegistry()
    registry.register("produce", produce)
    registry.register("consume", consume, requires_approval=True)
    repository = TaskRepository("sqlite:///:memory:")
    try:
        state = run_agent(
            '{"steps":[{"tool_name":"produce"},{"tool_name":"consume",'
            '"tool_args":{"data":{"$ref":1}}}]}',
            registry=registry,
            repository=repository,
        )
        stored = repository.get_task(state.task_id)
        assert state.steps[0].result == {"1": [2, 3]}
        assert stored.steps[0].result == state.steps[0].result
        for candidate in [state, stored]:
            approve_current_step(candidate)
            execute_plan(candidate, registry)
            assert candidate.status.value == "completed"
            assert candidate.result == "5"
    finally:
        repository.close()


def test_concurrent_duplicate_registration_preserves_one_definition():
    registry = ToolRegistry()

    def register_once(_):
        try:
            registry.register("add", add)
            return True
        except ValueError:
            return False

    with ThreadPoolExecutor(max_workers=4) as pool:
        assert sum(pool.map(register_once, range(8))) == 1
    assert len(registry.list_tools()) == 1


@pytest.mark.parametrize(
    "function,a,b,expected",
    [
        (add, 2, 3, 5),
        (add, -2, 3, 1),
        (multiply, -3, 4.5, -13.5),
        (subtract, 10, 2, 8),
        (divide, 10, 4, 2.5),
        (power, 2, 3, 8),
        (power, -2, 3, -8),
        (power, 2, -3, 0.125),
        (power, 0, 0, 1),
    ],
)
def test_calculator_operations(function, a, b, expected):
    assert function(a, b) == expected


@pytest.mark.parametrize(
    "function,a,b",
    [
        (divide, 1, 0),
        (add, True, 1),
        (add, "2", 1),
        (add, float("nan"), 1),
        (multiply, 1e100, 1e100),
        (power, 0, -1),
        (power, -2, 0.5),
        (power, 2, 1001),
        (power, 1e100, 1000),
    ],
)
def test_calculator_rejects_invalid_or_unbounded_work(function, a, b):
    with pytest.raises(ValueError):
        function(a, b)
