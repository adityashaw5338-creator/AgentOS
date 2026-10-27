"""AgentOS orchestration with durable planning and execution checkpoints."""

from __future__ import annotations

from agent_engine.executor import execute_plan
from agent_engine.planner import create_plan
from agent_engine.state import AgentState, AgentStatus
from agent_engine.storage.repository import ConcurrentUpdateError, TaskRepository, get_repository
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
    planner: str | None = None,
) -> AgentState:
    """Plan and save a goal, preserving failures and approval pauses in history."""
    state = AgentState(goal=goal, status=AgentStatus.PLANNING)
    registry = registry if registry is not None else build_registry()
    repository = repository if repository is not None else get_repository()
    # Record the goal before planning or executing anything. A killed process
    # leaves an inspectable task, including a provider call still in progress.
    repository.save_task(state)
    try:
        create_plan(state, registry, mode=planner)
        if require_approval:
            for step in state.steps:
                step.requires_approval = True
        if execute:
            state.status = AgentStatus.RUNNING
            repository.save_task(state)
            execute_plan(state, registry, checkpoint=repository.save_task)
    except ConcurrentUpdateError:
        # A cancellation/recovery in another client wins. Never overwrite it.
        raise
    except ValueError as error:
        state.status = AgentStatus.FAILED
        state.error = str(error)
        state.execution_log.append(f"Task failed: {error}")
    except Exception:
        state.status = AgentStatus.FAILED
        state.error = (
            "Planning or execution failed unexpectedly; inspect the saved task before retrying."
        )
        state.execution_log.append(state.error)
    repository.save_task(state)
    return state


def recover_task(state: AgentState, *, confirm_stopped: bool = False) -> AgentState:
    """Close an interrupted run without replaying a possibly completed side effect."""
    if not confirm_stopped:
        raise ValueError("Stop the worker first, then confirm it has stopped to recover this task.")
    if state.status not in {AgentStatus.PLANNING, AgentStatus.RUNNING}:
        raise ValueError("Only interrupted planning or running tasks can be recovered.")
    state.status = AgentStatus.FAILED
    state.error = (
        "Interrupted run closed by the operator. A tool may have completed before the interruption; "
        "review its effects before creating another task."
    )
    state.execution_log.append(state.error)
    return state
