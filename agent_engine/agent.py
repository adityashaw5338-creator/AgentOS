"""AgentOS orchestration: plan, optionally execute, then persist the task."""

from __future__ import annotations

from agent_engine.executor import execute_plan
from agent_engine.state import AgentState, AgentStatus
from agent_engine.storage.repository import TaskRepository, get_repository
from agent_engine.tool_planner import create_tool_plan
from agent_engine.tools.calculator import add, divide, multiply, power, subtract
from agent_engine.tools.registry import ToolRegistry


def build_registry() -> ToolRegistry:
    """Register the real calculator tools available in this first version."""
    registry = ToolRegistry()
    registry.register("add", add, "Add two numbers.")
    registry.register("multiply", multiply, "Multiply two numbers.")
    registry.register("subtract", subtract, "Subtract the second number from the first.")
    registry.register("divide", divide, "Divide the first number by the second.")
    registry.register("power", power, "Raise the first number to the power of the second.")
    return registry


def run_agent(
    goal: str,
    *,
    registry: ToolRegistry | None = None,
    repository: TaskRepository | None = None,
    execute: bool = True,
    require_approval: bool = False,
) -> AgentState:
    """Plan and save a goal, preserving failures and approval pauses in history."""
    state = AgentState(goal=goal)
    registry = registry if registry is not None else build_registry()
    repository = repository if repository is not None else get_repository()
    try:
        create_tool_plan(state, registry)
        if require_approval:
            for step in state.steps:
                step.requires_approval = True
        if execute:
            execute_plan(state, registry)
    except ValueError as error:
        state.status = AgentStatus.FAILED
        state.error = str(error)
        state.execution_log.append(f"Task failed: {error}")
    repository.save_task(state)
    return state
