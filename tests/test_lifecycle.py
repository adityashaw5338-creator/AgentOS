import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from fastapi.testclient import TestClient

from agent_engine import agent, cli
from agent_engine.api import Settings, create_app
from agent_engine.state import AgentState, AgentStatus
from agent_engine.storage.repository import ConcurrentUpdateError, TaskRepository
from agent_engine.tools.registry import ToolRegistry

TOKEN = "lifecycle-test-token-2026"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def repository(tmp_path):
    repository = TaskRepository(f"sqlite:///{(tmp_path / 'tasks.db').as_posix()}")
    yield repository
    repository.close()


def test_goal_is_durable_before_planning_starts(repository, monkeypatch):
    def interrupted_planner(state, registry, **kwargs):
        saved = repository.get_task(state.task_id)
        assert saved.status == AgentStatus.PLANNING
        assert saved.goal == "add 1 and 2"
        raise KeyboardInterrupt

    monkeypatch.setattr(agent, "create_plan", interrupted_planner)
    with pytest.raises(KeyboardInterrupt):
        agent.run_agent("add 1 and 2", repository=repository)
    assert repository.list_tasks()[0].status == AgentStatus.PLANNING


def test_completed_steps_and_started_attempt_survive_interruption(repository):
    registry = ToolRegistry()

    def first() -> int:
        saved = repository.list_tasks()[0]
        assert saved.status == AgentStatus.RUNNING
        assert saved.steps[0].attempts == 1
        return 7

    def interrupted() -> int:
        saved = repository.list_tasks()[0]
        assert saved.status == AgentStatus.RUNNING
        assert saved.steps[0].completed
        assert saved.steps[0].result == 7
        assert saved.steps[1].attempts == 1
        raise SystemExit(2)

    registry.register("first", first)
    registry.register("interrupted", interrupted)
    goal = json.dumps({"steps": [{"tool_name": "first"}, {"tool_name": "interrupted"}]})
    with pytest.raises(SystemExit):
        agent.run_agent(goal, registry=registry, repository=repository)
    reopened = TaskRepository(repository.database_url)
    try:
        saved = reopened.list_tasks()[0]
        assert saved.current_step == 1
        assert saved.steps[0].completed
        assert not saved.steps[1].completed
        assert saved.status == AgentStatus.RUNNING
        agent.recover_task(saved, confirm_stopped=True)
        reopened.save_task(saved)
        assert reopened.get_task(saved.task_id).steps[0].result == 7
        assert reopened.get_task(saved.task_id).status == AgentStatus.FAILED
    finally:
        reopened.close()


def test_cancel_during_planning_prevents_any_tool_execution(repository, monkeypatch):
    original = agent.create_plan

    def cancelled_during_plan(state, registry, **kwargs):
        saved = repository.get_task(state.task_id)
        saved.status = AgentStatus.CANCELLED
        repository.save_task(saved)
        return original(state, registry, **kwargs)

    monkeypatch.setattr(agent, "create_plan", cancelled_during_plan)
    with pytest.raises(ConcurrentUpdateError):
        agent.run_agent("add 1 and 2", repository=repository)
    saved = repository.list_tasks()[0]
    assert saved.status == AgentStatus.CANCELLED
    assert saved.result is None


def test_failed_checkpoint_never_executes_or_retries_tool(repository, monkeypatch):
    calls = []
    registry = ToolRegistry()
    registry.register("record", lambda: calls.append("effect"))
    original = repository.save_task

    def conflicting_checkpoint(state):
        if state.steps and state.steps[0].attempts:
            raise ConcurrentUpdateError("Claim no longer belongs to this runner.")
        return original(state)

    monkeypatch.setattr(repository, "save_task", conflicting_checkpoint)
    with pytest.raises(ConcurrentUpdateError):
        agent.run_agent(
            '{"steps":[{"tool_name":"record"}]}', registry=registry, repository=repository
        )
    assert calls == []


def test_failure_saving_result_stops_before_next_tool(repository, monkeypatch):
    calls = []
    registry = ToolRegistry()

    def record() -> int:
        calls.append("effect")
        return len(calls)

    registry.register("record", record)
    original = repository.save_task
    failed = False

    def failed_result_checkpoint(state):
        nonlocal failed
        if state.current_step == 1 and not failed:
            failed = True
            raise OSError("Temporary storage failure")
        return original(state)

    monkeypatch.setattr(repository, "save_task", failed_result_checkpoint)
    result = agent.run_agent(
        '{"steps":[{"tool_name":"record"},{"tool_name":"record"}]}',
        registry=registry,
        repository=repository,
    )
    assert calls == ["effect"]
    assert result.status == AgentStatus.FAILED
    assert result.steps[0].completed
    assert result.steps[1].attempts == 0


def test_unexpected_planning_failure_is_saved_without_private_details(repository, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("private-debug-value")

    monkeypatch.setattr(agent, "create_plan", broken)
    state = agent.run_agent("add 1 and 2", repository=repository)
    saved = repository.get_task(state.task_id)
    assert saved.status == AgentStatus.FAILED
    assert "private-debug-value" not in saved.model_dump_json()


def test_slow_tool_does_not_block_other_tasks_or_history(repository):
    entered, release = Event(), Event()
    registry = agent.build_registry()

    def slow() -> str:
        entered.set()
        assert release.wait(10)
        return "done"

    registry.register("slow", slow)
    app = create_app(Settings(api_token=TOKEN), repository, registry)
    with TestClient(app) as client, ThreadPoolExecutor(max_workers=2) as pool:
        slow_request = pool.submit(
            client.post,
            "/api/tasks",
            headers=AUTH,
            json={"goal": '{"steps":[{"tool_name":"slow"}]}'},
        )
        try:
            assert entered.wait(5)
            fast_request = pool.submit(
                client.post,
                "/api/tasks",
                headers=AUTH,
                json={"goal": "add 2 and 3"},
            )
            assert fast_request.result(timeout=3).json()["result"] == "5.0"
            history = client.get("/api/tasks", headers=AUTH).json()["tasks"]
            assert any(task["status"] == "running" for task in history)
        finally:
            release.set()
        assert slow_request.result(timeout=3).json()["status"] == "completed"


def test_recovery_requires_acknowledgement_current_revision_and_auth(repository):
    state = AgentState(goal="interrupted", status=AgentStatus.RUNNING)
    repository.save_task(state)
    with TestClient(create_app(Settings(api_token=TOKEN), repository)) as client:
        url = f"/api/tasks/{state.task_id}/recover"
        assert client.post(url, json={"revision": state.revision}).status_code == 401
        assert client.post(url, headers=AUTH, json={"revision": state.revision}).status_code == 409
        body = {"revision": state.revision, "confirm_stopped": "yes"}
        assert client.post(url, headers=AUTH, json=body).status_code == 422
        body["confirm_stopped"] = True
        response = client.post(url, headers=AUTH, json=body)
        assert response.status_code == 200
        assert response.json()["status"] == "failed"
        assert "review" in response.json()["error"]
        assert client.post(url, headers=AUTH, json=body).status_code == 409
        body["revision"] = response.json()["revision"]
        assert client.post(url, headers=AUTH, json=body).status_code == 409
        assert (
            client.post(
                f"/api/tasks/{state.task_id}/execute",
                headers=AUTH,
                json={"revision": body["revision"]},
            ).status_code
            == 409
        )


def test_cli_closes_interruption_without_rerunning(repository, monkeypatch, capsys):
    state = AgentState(goal="interrupted", status=AgentStatus.RUNNING)
    repository.save_task(state)
    monkeypatch.setattr(cli, "get_repository", lambda: repository)
    assert cli.main(["recover", state.task_id]) == 1
    assert "confirm" in capsys.readouterr().err
    assert cli.main(["recover", state.task_id, "--confirm-stopped", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "failed"
    assert cli.main(["resume", state.task_id]) == 1


def test_cli_planner_flag_preserved_for_negative_expressions(repository, monkeypatch, capsys):
    monkeypatch.setattr(cli, "get_repository", lambda: repository)
    monkeypatch.setenv("AGENTOS_PLANNER", "invalid-mode")
    assert cli.main(["run", "-(2 + 3)", "--planner", "local", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["result"] == "-5.0"


def test_non_interrupted_task_cannot_be_recovered(repository):
    state = agent.run_agent("add 1 and 2", repository=repository)
    with pytest.raises(ValueError, match="interrupted"):
        agent.recover_task(state, confirm_stopped=True)
    assert repository.get_task(state.task_id).status == AgentStatus.COMPLETED
