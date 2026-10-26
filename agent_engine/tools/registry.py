"""A typed, explicitly registered set of tools available to an agent."""

import inspect
import json
import math
import re
from dataclasses import dataclass
from threading import RLock
from typing import Any, Callable, get_type_hints

from pydantic import BaseModel, ConfigDict, ValidationError, create_model


def _validate_json_values(value: Any, depth: int = 0) -> None:
    """Check numbers in untyped containers as well as declared float fields."""
    if depth > 64:
        raise ValueError("Tool data nesting exceeds 64 levels.")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Tool data must contain finite real numbers.")
    if isinstance(value, dict):
        for key, child in value.items():
            _validate_json_values(key, depth + 1)
            _validate_json_values(child, depth + 1)
    elif isinstance(value, (list, tuple, set, frozenset)):
        for child in value:
            _validate_json_values(child, depth + 1)


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    function: Callable[..., Any]
    description: str
    requires_approval: bool
    args_model: type[BaseModel]


class ToolRegistry:
    """Infer argument schemas without permitting arbitrary function execution."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}
        self._lock = RLock()

    def register(
        self,
        name: str,
        function: Callable[..., Any],
        description: str = "",
        requires_approval: bool = False,
    ) -> ToolDefinition:
        if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", name):
            raise ValueError("Tool names must use lowercase letters, numbers, and underscores.")
        if not callable(function) or inspect.iscoroutinefunction(function):
            raise ValueError("Tools must be synchronous callable functions.")
        if not isinstance(requires_approval, bool):
            raise ValueError("requires_approval must be a boolean.")

        with self._lock:
            if name in self._tools:
                raise ValueError(f"Tool '{name}' is already registered.")
            try:
                signature = inspect.signature(function)
                hints = get_type_hints(function)
            except (TypeError, ValueError, NameError) as error:
                raise ValueError(f"Cannot inspect tool '{name}': {error}") from error

            fields: dict[str, Any] = {}
            for parameter in signature.parameters.values():
                if parameter.kind not in (
                    inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    inspect.Parameter.KEYWORD_ONLY,
                ):
                    raise ValueError("Tools cannot have positional-only or variadic arguments.")
                annotation = hints.get(parameter.name, parameter.annotation)
                if annotation is inspect.Parameter.empty:
                    raise ValueError(
                        f"Tool argument '{parameter.name}' must have a type annotation."
                    )
                if parameter.default is not inspect.Parameter.empty:
                    try:
                        _validate_json_values(parameter.default)
                    except ValueError as error:
                        raise ValueError(
                            f"Tool '{name}' has an invalid default for '{parameter.name}': {error}"
                        ) from error
                default = ... if parameter.default is inspect.Parameter.empty else parameter.default
                fields[parameter.name] = (annotation, default)

            try:
                args_model = create_model(
                    f"{name.title().replace('_', '')}Arguments",
                    __config__=ConfigDict(
                        extra="forbid", strict=True, allow_inf_nan=False, validate_default=True
                    ),
                    **fields,
                )
                json.dumps(args_model.model_json_schema(), allow_nan=False)
            except Exception as error:
                raise ValueError(
                    f"Tool '{name}' has unsupported argument types or defaults: {error}"
                ) from error

            definition = ToolDefinition(
                name=name,
                function=function,
                description=description or inspect.getdoc(function) or "",
                requires_approval=requires_approval,
                args_model=args_model,
            )
            self._tools[name] = definition
            return definition

    def get(self, name: str) -> ToolDefinition:
        with self._lock:
            try:
                return self._tools[name]
            except KeyError as error:
                raise ValueError(f"Unknown tool: '{name}'.") from error

    def _validated_model(self, name: str, arguments: dict[str, Any]) -> BaseModel:
        definition = self.get(name)
        if not isinstance(arguments, dict):
            raise ValueError("Tool arguments must be an object.")
        try:
            _validate_json_values(arguments)
            validated = definition.args_model.model_validate(arguments)
            _validate_json_values(validated.model_dump())
            return validated
        except (ValidationError, ValueError) as error:
            raise ValueError(f"Invalid arguments for '{name}': {error}") from error

    def validate_arguments(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Return snapshot arguments while retaining typed values for tool invocation."""
        return self._validated_model(name, arguments).model_dump()

    def execute(self, name: str, /, **arguments: Any) -> Any:
        definition = self.get(name)
        validated = self._validated_model(name, arguments)
        # model_dump flattens nested models; a typed callable needs their instances.
        values = {key: getattr(validated, key) for key in definition.args_model.model_fields}
        result = definition.function(**values)
        try:
            _validate_json_values(result)
            # References must see the same JSON types before and after a task
            # is saved. Tuples become lists and object keys become strings.
            return json.loads(json.dumps(result, allow_nan=False))
        except (TypeError, ValueError, OverflowError, RecursionError) as error:
            raise ValueError(f"Tool '{name}' returned a non-JSON or non-finite result.") from error

    def list_tools(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                {
                    "name": definition.name,
                    "description": definition.description,
                    "requires_approval": definition.requires_approval,
                    "parameters": definition.args_model.model_json_schema(),
                }
                for definition in self._tools.values()
            ]

    def get_schemas(self) -> dict[str, dict[str, Any]]:
        return {tool["name"]: tool["parameters"] for tool in self.list_tools()}
