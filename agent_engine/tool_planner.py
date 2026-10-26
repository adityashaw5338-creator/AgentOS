"""Compile a bounded calculation or explicit tool plan into executable steps.

The built-in planner is deliberately deterministic. It does not pretend to be
an LLM and never evaluates Python supplied by a user.
"""

from __future__ import annotations

import ast
import json
import math
import re
from typing import Any

from pydantic import TypeAdapter, ValidationError

from agent_engine.state import AgentState, AgentStatus, PlanStep
from agent_engine.tools.registry import ToolRegistry

MAX_STEPS = 32
MAX_GOAL_LENGTH = 4000
MAX_AST_NODES = 160
MAX_ARGUMENT_DEPTH = 64
NUMBER = r"([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?)"
_OPERATORS = {
    ast.Add: "add",
    ast.Sub: "subtract",
    ast.Mult: "multiply",
    ast.Div: "divide",
    ast.Pow: "power",
}
_UNSUPPORTED = (
    "This planner supports arithmetic and explicit JSON tool plans. "
    "Try 'add 2 and 3', 'calculate (2 + 3) * 4', or a JSON object with a 'steps' list."
)


def _number(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Calculations require real numbers, not booleans or strings.")
    try:
        result = float(value)
    except (OverflowError, ValueError) as error:
        raise ValueError("Number is outside the supported finite range.") from error
    if not math.isfinite(result):
        raise ValueError("Calculations require finite real numbers.")
    return result


def _references(value: Any, previous_ids: set[int], depth: int = 0) -> bool:
    """Check reference shape and ordering recursively; return whether any exist."""
    if depth > MAX_ARGUMENT_DEPTH:
        raise ValueError(f"Tool arguments cannot be nested more than {MAX_ARGUMENT_DEPTH} levels.")
    found = False
    if isinstance(value, dict):
        if "$ref" in value:
            reference = value["$ref"]
            if (
                set(value) != {"$ref"}
                or isinstance(reference, bool)
                or not isinstance(reference, int)
                or reference not in previous_ids
            ):
                raise ValueError("A '$ref' must contain only the integer ID of a previous step.")
            return True
        for child in value.values():
            found = _references(child, previous_ids, depth + 1) or found
    elif isinstance(value, list):
        for child in value:
            found = _references(child, previous_ids, depth + 1) or found
    return found


def _validated_args(
    registry: ToolRegistry,
    name: str,
    arguments: dict[str, Any],
    previous_ids: set[int],
) -> dict[str, Any]:
    tool = registry.get(name)
    if not _references(arguments, previous_ids):
        return registry.validate_arguments(name, arguments)

    # References are resolved by the executor. Validate every value available
    # now, and check required/unknown fields without guessing reference results.
    fields = tool.args_model.model_fields
    unknown = set(arguments) - set(fields)
    if unknown:
        raise ValueError(f"Unexpected arguments for '{name}': {', '.join(sorted(unknown))}.")
    missing = [key for key, field in fields.items() if field.is_required() and key not in arguments]
    if missing:
        raise ValueError(f"Missing arguments for '{name}': {', '.join(missing)}.")
    validated = dict(arguments)
    for key, value in arguments.items():
        if not _references(value, previous_ids):
            try:
                validated[key] = TypeAdapter(fields[key].rebuild_annotation()).validate_python(
                    value, strict=True
                )
            except ValidationError as error:
                raise ValueError(f"Invalid argument '{key}' for '{name}': {error}") from error
            _finite_values(validated[key])
    return validated


def _finite_values(value: Any, depth: int = 0) -> None:
    if depth > MAX_ARGUMENT_DEPTH:
        raise ValueError(f"Tool arguments cannot be nested more than {MAX_ARGUMENT_DEPTH} levels.")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Tool arguments must contain finite real numbers.")
    if isinstance(value, dict):
        for child in value.values():
            _finite_values(child, depth + 1)
    elif isinstance(value, list):
        for child in value:
            _finite_values(child, depth + 1)


def _step(
    registry: ToolRegistry,
    step_id: int,
    tool_name: str,
    arguments: dict[str, Any],
    previous_ids: set[int],
    description: str | None = None,
    requires_approval: bool = False,
) -> PlanStep:
    if not isinstance(tool_name, str) or not tool_name:
        raise ValueError("Every step requires a nonempty 'tool_name'.")
    if not isinstance(arguments, dict):
        raise ValueError("Every step's 'tool_args' must be a JSON object.")
    tool = registry.get(tool_name)
    args = _validated_args(registry, tool_name, arguments, previous_ids)
    return PlanStep(
        step_id=step_id,
        description=description or f"Run {tool_name}.",
        tool_name=tool_name,
        tool_args=args,
        requires_approval=requires_approval or tool.requires_approval,
    )


def _invalid_json_number(value: str) -> Any:
    raise ValueError(f"Invalid JSON number: {value}.")


def _json_plan(goal: str, registry: ToolRegistry) -> list[PlanStep]:
    try:
        data = json.loads(goal, parse_constant=_invalid_json_number)
    except (json.JSONDecodeError, RecursionError) as error:
        raise ValueError("The explicit plan must be valid JSON.") from error
    if not isinstance(data, dict) or set(data) != {"steps"}:
        raise ValueError("An explicit plan must be an object containing only a 'steps' list.")
    raw_steps = data["steps"]
    if not isinstance(raw_steps, list) or not 1 <= len(raw_steps) <= MAX_STEPS:
        raise ValueError(f"A plan requires between 1 and {MAX_STEPS} steps.")

    allowed = {"step_id", "description", "tool_name", "tool_args", "requires_approval"}
    previous_ids: set[int] = set()
    result = []
    for index, raw in enumerate(raw_steps, 1):
        if not isinstance(raw, dict) or set(raw) - allowed:
            raise ValueError(
                "Plan steps may contain only step_id, description, tool_name, tool_args, and requires_approval."
            )
        step_id = raw.get("step_id", index)
        if (
            isinstance(step_id, bool)
            or not isinstance(step_id, int)
            or step_id < 1
            or step_id in previous_ids
        ):
            raise ValueError("Step IDs must be unique positive integers.")
        description = raw.get("description")
        if description is not None and (
            not isinstance(description, str) or not description.strip()
        ):
            raise ValueError("A step description must be a nonempty string.")
        approval = raw.get("requires_approval", False)
        if not isinstance(approval, bool):
            raise ValueError("'requires_approval' must be a JSON boolean.")
        result.append(
            _step(
                registry,
                step_id,
                raw.get("tool_name"),
                raw.get("tool_args", {}),
                previous_ids,
                description,
                approval,
            )
        )
        previous_ids.add(step_id)
    return result


def _natural_request(goal: str) -> tuple[str, dict[str, float]] | None:
    text = re.sub(r"^please\s+", "", goal, flags=re.IGNORECASE).strip()
    text = re.sub(r"^(?:calculate|compute)\s+", "", text, flags=re.IGNORECASE).rstrip("?!").strip()
    patterns = [
        (rf"(?:add|sum)\s+{NUMBER}\s+(?:and|to)\s+{NUMBER}\.?", "add", False),
        (rf"{NUMBER}\s+plus\s+{NUMBER}\.?", "add", False),
        (rf"multiply\s+{NUMBER}\s+(?:by|and)\s+{NUMBER}\.?", "multiply", False),
        (rf"{NUMBER}\s+(?:times|multiplied by)\s+{NUMBER}\.?", "multiply", False),
        (rf"subtract\s+{NUMBER}\s+from\s+{NUMBER}\.?", "subtract", True),
        (rf"{NUMBER}\s+minus\s+{NUMBER}\.?", "subtract", False),
        (rf"divide\s+{NUMBER}\s+by\s+{NUMBER}\.?", "divide", False),
        (rf"{NUMBER}\s+divided by\s+{NUMBER}\.?", "divide", False),
        (rf"raise\s+{NUMBER}\s+to\s+(?:the\s+)?power\s+(?:of\s+)?{NUMBER}\.?", "power", False),
        (rf"{NUMBER}\s+to\s+(?:the\s+)?power\s+(?:of\s+)?{NUMBER}\.?", "power", False),
    ]
    for pattern, name, reverse in patterns:
        match = re.fullmatch(pattern, text, flags=re.IGNORECASE)
        if match:
            first, second = (_number(float(value)) for value in match.groups())
            a, b = (second, first) if reverse else (first, second)
            return name, {"a": a, "b": b}
    return None


def _expression_plan(goal: str, registry: ToolRegistry) -> list[PlanStep]:
    expression = re.sub(
        r"^(?:please\s+)?(?:calculate|compute)\s+", "", goal, flags=re.IGNORECASE
    ).strip()
    try:
        tree = ast.parse(expression, mode="eval")
    except (SyntaxError, RecursionError, ValueError) as error:
        raise ValueError(_UNSUPPORTED) from error
    if sum(1 for _ in ast.walk(tree)) > MAX_AST_NODES:
        raise ValueError("Calculation is too complex; use a smaller expression.")
    steps: list[PlanStep] = []

    def emit(name: str, a: Any, b: Any) -> dict[str, int]:
        if len(steps) >= MAX_STEPS:
            raise ValueError(f"Calculations are limited to {MAX_STEPS} tool steps.")
        step_id = len(steps) + 1
        steps.append(
            _step(
                registry,
                step_id,
                name,
                {"a": a, "b": b},
                {step.step_id for step in steps},
                f"Calculate {name}.",
            )
        )
        return {"$ref": step_id}

    def visit(node: ast.AST) -> Any:
        if isinstance(node, ast.Constant):
            return _number(node.value)
        if isinstance(node, ast.BinOp) and type(node.op) in _OPERATORS:
            return emit(_OPERATORS[type(node.op)], visit(node.left), visit(node.right))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = visit(node.operand)
            if isinstance(node.op, ast.UAdd):
                return value
            return emit("multiply", value, -1.0) if isinstance(value, dict) else -value
        raise ValueError(_UNSUPPORTED)

    value = visit(tree.body)
    if not steps:
        emit("add", value, 0.0)
    return steps


def create_tool_plan(state: AgentState, registry: ToolRegistry) -> AgentState:
    """Replace the state's plan with validated executable tool calls."""
    goal = state.goal.strip()
    if not goal:
        raise ValueError("Task goal cannot be empty.")
    if len(goal) > MAX_GOAL_LENGTH:
        raise ValueError(f"Task goals are limited to {MAX_GOAL_LENGTH} characters.")
    state.status = AgentStatus.PLANNING
    if goal.startswith("{"):
        steps = _json_plan(goal, registry)
    else:
        request = _natural_request(goal)
        steps = (
            [_step(registry, 1, *request, set())] if request else _expression_plan(goal, registry)
        )
    state.steps = steps
    state.current_step = 0
    state.result = None
    state.error = None
    state.status = AgentStatus.PENDING
    state.execution_log.append(f"Planned {len(steps)} tool step(s).")
    return state
