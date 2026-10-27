"""Public planning entry point retained from the original project."""

from __future__ import annotations

import os

from agent_engine.state import AgentState
from agent_engine.tool_planner import create_tool_plan
from agent_engine.tools.registry import ToolRegistry


def _mode(mode: str | None = None) -> str:
    selected = os.environ.get("AGENTOS_PLANNER", "local") if mode is None else mode
    if selected not in {"local", "openai"}:
        raise ValueError("AGENTOS_PLANNER must be 'local' or 'openai'.")
    return selected


def planner_info() -> dict:
    """Return configuration availability, without a network request or credentials."""
    from agent_engine.ai_planner import OpenAISettings

    message = None
    try:
        default = _mode()
    except ValueError as error:
        default = None
        message = str(error)
    try:
        settings = OpenAISettings.from_env()
        available = True
        model = settings.model
        timeout = settings.timeout
    except ValueError as error:
        available = False
        model = None
        timeout = None
        message = message or str(error)
    return {
        "default": default,
        "openai_available": available,
        "model": model,
        "timeout_seconds": timeout,
        "message": message,
    }


def create_plan(
    state: AgentState,
    registry: ToolRegistry | None = None,
    *,
    mode: str | None = None,
) -> AgentState:
    """Build a validated local plan, or explicitly opt into configured AI planning."""
    selected = _mode(mode)
    if registry is None:
        from agent_engine.agent import build_registry

        registry = build_registry()
    if selected == "local":
        return create_tool_plan(state, registry)
    from agent_engine.ai_planner import OpenAIPlanner

    return OpenAIPlanner.from_env().create_plan(state, registry)
