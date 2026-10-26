"""Public planning entry point retained from the original project."""

from __future__ import annotations

from agent_engine.state import AgentState
from agent_engine.tool_planner import create_tool_plan
from agent_engine.tools.registry import ToolRegistry


def create_plan(state: AgentState, registry: ToolRegistry | None = None) -> AgentState:
    """Build an executable plan using the default or supplied tool registry."""
    if registry is None:
        from agent_engine.agent import build_registry

        registry = build_registry()
    return create_tool_plan(state, registry)
