"""Command-line task runner, history browser, and local dashboard server."""

from __future__ import annotations

import argparse
import json
import re
import sys

from agent_engine.agent import build_registry, run_agent
from agent_engine.executor import approve_current_step, execute_plan
from agent_engine.state import AgentState, AgentStatus
from agent_engine.storage.repository import ConcurrentUpdateError, TaskRepository, get_repository


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AgentOS - a controlled tool execution engine.")
    commands = parser.add_subparsers(dest="command")
    for name, help_text in (
        ("run", "Plan and execute a goal."),
        ("plan", "Save a plan without executing tools."),
    ):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("goal", nargs="+", help="Calculation or explicit JSON plan.")
        command.add_argument("--json", action="store_true", help="Print the complete task as JSON.")
        command.add_argument(
            "--require-approval", action="store_true", help="Require approval before every step."
        )
    history = commands.add_parser("history", help="List saved tasks.")
    history.add_argument("--json", action="store_true")
    history.add_argument("--limit", type=int, default=100)
    history.add_argument("--offset", type=int, default=0, help="Skip this many saved tasks.")
    history.add_argument("--status", choices=[status.value for status in AgentStatus])
    history.add_argument("--search", default=None)
    for name, help_text in (
        ("show", "Show a saved task."),
        ("approve", "Approve and resume the current step."),
        ("cancel", "Cancel a pending task."),
        ("resume", "Execute a saved pending plan."),
    ):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("task_id")
        command.add_argument("--json", action="store_true")
    tools = commands.add_parser("tools", help="List registered tools and argument schemas.")
    tools.add_argument("--json", action="store_true")
    server = commands.add_parser("serve", help="Start the dashboard and protected API.")
    server.add_argument("--host", default="127.0.0.1")
    server.add_argument("--port", type=int, default=8000)
    return parser


def _print_task(task: AgentState, as_json: bool) -> None:
    if as_json:
        print(task.model_dump_json(indent=2))
        return
    print(f"Task ID: {task.task_id}\nGoal: {task.goal}\nStatus: {task.status.value}")
    if task.result is not None:
        print(f"Result: {task.result}")
    if task.error:
        print(f"Error: {task.error}")
    if task.steps:
        print("Plan:")
        for step in task.steps:
            status = "completed" if step.completed else "pending"
            approval = (
                " (approval required)" if step.requires_approval and not step.approved else ""
            )
            print(
                f"- Step {step.step_id}: {step.tool_name} "
                f"{json.dumps(step.tool_args)} [{status}]{approval}"
            )
    if task.execution_log:
        print("Execution history:")
        for event in task.execution_log:
            print(f"- {event}")


def _execute_saved_plan(state: AgentState, repository: TaskRepository) -> None:
    """Claim a pending task and persist failures that escape normal tool handling."""
    state.status = AgentStatus.RUNNING
    repository.save_task(state)
    try:
        execute_plan(state, build_registry())
    except Exception:
        state.status = AgentStatus.FAILED
        state.error = "Execution failed unexpectedly; the task was stopped."
        state.execution_log.append(state.error)
    repository.save_task(state)


def main(argv: list[str] | None = None) -> int:
    """Return a process exit code; callers may supply arguments for embedding."""
    parser = _parser()
    arguments = list(sys.argv[1:] if argv is None else argv)
    # Preserve the original CLI: agentos "add 2 and 3" and agentos add 2 and 3.
    known = {"run", "plan", "history", "show", "approve", "cancel", "resume", "tools", "serve"}
    if (
        arguments
        and arguments[0] not in known
        and (not arguments[0].startswith("-") or re.match(r"-[\d.(]", arguments[0]))
    ):
        arguments.insert(0, "run")
    if arguments and arguments[0] in {"run", "plan"} and "--" not in arguments:
        # argparse mistakes a quoted expression beginning with a minus sign for
        # an option. Preserve flags, then mark the calculation as positional.
        if any(re.match(r"-[\d.(]", value) for value in arguments[1:]):
            flags = [value for value in arguments[1:] if value in {"--json", "--require-approval"}]
            goal_parts = [
                value for value in arguments[1:] if value not in {"--json", "--require-approval"}
            ]
            arguments = [arguments[0], *flags, "--", *goal_parts]
    args = parser.parse_args(arguments)
    if args.command is None:
        parser.print_help()
        return 0
    if args.command == "history":
        if not 1 <= args.limit <= 500:
            parser.error("History limit must be between 1 and 500.")
        if args.offset < 0:
            parser.error("History offset must be nonnegative.")
    if args.command == "serve":
        if not 1 <= args.port <= 65535:
            parser.error("Port must be between 1 and 65535.")
        import uvicorn

        from agent_engine.api import Settings, create_app

        try:
            settings = Settings.from_env()
            app = create_app(settings=settings)
        except ValueError as error:
            print(f"Error: {error}", file=sys.stderr)
            return 1
        print(
            f"Dashboard: http://{args.host}:{args.port}\nAccess token: {settings.api_token}",
            flush=True,
        )
        uvicorn.run(app, host=args.host, port=args.port)
        return 0
    if args.command == "tools":
        tools = build_registry().list_tools()
        if args.json:
            print(json.dumps(tools, indent=2))
        else:
            for tool in tools:
                print(f"{tool['name']}: {tool['description']}")
        return 0

    repository = get_repository()
    try:
        if args.command in {"run", "plan"}:
            state = run_agent(
                " ".join(args.goal),
                repository=repository,
                execute=args.command == "run",
                require_approval=args.require_approval,
            )
        elif args.command == "history":
            tasks = repository.list_tasks(
                limit=args.limit, offset=args.offset, status=args.status, search=args.search
            )
            if args.json:
                print(json.dumps([task.model_dump(mode="json") for task in tasks], indent=2))
            elif not tasks:
                print("No saved tasks found.")
            else:
                for index, task in enumerate(tasks):
                    if index:
                        print()
                    _print_task(task, False)
            return 0
        else:
            state = repository.get_task(args.task_id)
            if state is None:
                print(f"Task not found: {args.task_id}", file=sys.stderr)
                return 1
            if args.command == "approve":
                approve_current_step(state)
                _execute_saved_plan(state, repository)
            elif args.command == "resume":
                if state.status != AgentStatus.PENDING:
                    raise ValueError(
                        "Only pending plans can be resumed; waiting tasks need approval."
                    )
                _execute_saved_plan(state, repository)
            elif args.command == "cancel":
                if state.status not in {
                    AgentStatus.PENDING,
                    AgentStatus.PLANNING,
                    AgentStatus.WAITING_FOR_APPROVAL,
                }:
                    raise ValueError("Only a pending or waiting task can be cancelled.")
                state.status = AgentStatus.CANCELLED
                state.error = None
                state.execution_log.append("Task cancelled by the user.")
                repository.save_task(state)
        _print_task(state, args.json)
        return 1 if state.status == AgentStatus.FAILED else 0
    except ConcurrentUpdateError:
        print(
            "Error: This task changed in another process. Reload it before trying again.",
            file=sys.stderr,
        )
        return 1
    except ValueError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1


def entrypoint() -> None:
    raise SystemExit(main())


if __name__ == "__main__":
    entrypoint()
