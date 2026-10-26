import json

import pytest

from agent_engine import cli
from agent_engine.storage.repository import ConcurrentUpdateError, TaskRepository


@pytest.fixture
def repository(monkeypatch):
    repository = TaskRepository(database_url="sqlite:///:memory:")
    monkeypatch.setattr(cli, "get_repository", lambda: repository)
    yield repository
    repository.close()


def test_legacy_goal_and_json_history(repository, capsys):
    assert cli.main(["add", "2", "and", "3", "--json"]) == 0
    task = json.loads(capsys.readouterr().out)
    assert task["result"] == "5.0"
    assert cli.main(["history", "--json"]) == 0
    history = json.loads(capsys.readouterr().out)
    assert history[0]["task_id"] == task["task_id"]
    assert cli.main(["show", task["task_id"], "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["result"] == "5.0"


def test_failed_task_returns_nonzero_exit_code(repository, capsys):
    assert cli.main(["run", "divide 1 by 0", "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "failed"


@pytest.mark.parametrize("arguments", [["-3 * 2", "--json"], ["run", "-(2 + 3)", "--json"]])
def test_negative_expressions_can_be_run_without_argument_escaping(repository, capsys, arguments):
    assert cli.main(arguments) == 0
    assert json.loads(capsys.readouterr().out)["result"] in {"-6.0", "-5.0"}


def test_approval_resume_and_cancel_work_with_saved_tasks(repository, capsys):
    assert cli.main(["run", "(2 + 3) * 4", "--require-approval", "--json"]) == 0
    task = json.loads(capsys.readouterr().out)
    assert task["status"] == "waiting_for_approval"
    assert cli.main(["approve", task["task_id"], "--json"]) == 0
    task = json.loads(capsys.readouterr().out)
    assert task["current_step"] == 1
    assert task["status"] == "waiting_for_approval"
    assert cli.main(["cancel", task["task_id"], "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "cancelled"
    assert cli.main(["approve", task["task_id"]]) == 1
    assert "waiting" in capsys.readouterr().err


def test_plan_only_can_be_resumed(repository, capsys):
    assert cli.main(["plan", "add 2 and 3", "--json"]) == 0
    task = json.loads(capsys.readouterr().out)
    assert task["status"] == "pending"
    assert cli.main(["resume", task["task_id"], "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["result"] == "5.0"


def test_history_pages_do_not_repeat_saved_tasks(repository, capsys):
    for value in range(3):
        assert cli.main(["plan", f"add {value} and 1", "--json"]) == 0
        capsys.readouterr()
    assert cli.main(["history", "--limit", "2", "--json"]) == 0
    first_page = json.loads(capsys.readouterr().out)
    assert cli.main(["history", "--limit", "2", "--offset", "2", "--json"]) == 0
    second_page = json.loads(capsys.readouterr().out)
    assert len(first_page) == 2
    assert len(second_page) == 1
    assert {task["task_id"] for task in first_page}.isdisjoint(
        task["task_id"] for task in second_page
    )


@pytest.mark.parametrize("arguments", [["--limit", "501"], ["--offset", "-1"]])
def test_invalid_history_pagination_is_rejected_before_opening_database(monkeypatch, arguments):
    calls = []
    monkeypatch.setattr(cli, "get_repository", lambda: calls.append(True))
    with pytest.raises(SystemExit) as error:
        cli.main(["history", *arguments])
    assert error.value.code == 2
    assert calls == []


@pytest.mark.parametrize("action", ["resume", "approve"])
def test_unexpected_saved_execution_failure_is_persisted(repository, capsys, monkeypatch, action):
    arguments = ["plan", "add 2 and 3", "--json"]
    if action == "approve":
        arguments = ["run", "add 2 and 3", "--require-approval", "--json"]
    assert cli.main(arguments) == 0
    task = json.loads(capsys.readouterr().out)

    def broken_executor(*args, **kwargs):
        raise RuntimeError("Unexpected internal failure")

    monkeypatch.setattr(cli, "execute_plan", broken_executor)
    assert cli.main([action, task["task_id"], "--json"]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "failed"
    assert "Execution failed unexpectedly" in result["error"]
    saved = repository.get_task(task["task_id"])
    assert saved.status.value == "failed"
    assert saved.error == result["error"]
    assert saved.revision > task["revision"]


def test_conflicting_claim_prevents_tool_execution(repository, capsys, monkeypatch):
    cli.main(["plan", "add 2 and 3", "--json"])
    task = json.loads(capsys.readouterr().out)
    calls = []

    def conflict(state):
        raise ConcurrentUpdateError("Task changed.")

    monkeypatch.setattr(repository, "save_task", conflict)
    monkeypatch.setattr(cli, "execute_plan", lambda *args, **kwargs: calls.append(args))
    assert cli.main(["resume", task["task_id"]]) == 1
    assert calls == []
    assert "Reload" in capsys.readouterr().err


def test_completed_tasks_cannot_be_cancelled(repository, capsys):
    cli.main(["run", "add 1 and 1", "--json"])
    task = json.loads(capsys.readouterr().out)
    assert cli.main(["cancel", task["task_id"]]) == 1
    assert "cancelled" in capsys.readouterr().err


def test_missing_task_and_empty_history(repository, capsys):
    assert cli.main(["show", "missing"]) == 1
    assert "not found" in capsys.readouterr().err
    assert cli.main(["history"]) == 0
    assert "No saved tasks" in capsys.readouterr().out


def test_tools_schema_is_available_without_running_a_task(capsys):
    assert cli.main(["tools", "--json"]) == 0
    tools = json.loads(capsys.readouterr().out)
    assert {tool["name"] for tool in tools} == {"add", "subtract", "multiply", "divide", "power"}
    assert tools[0]["parameters"]["additionalProperties"] is False


def test_help_does_not_create_tasks(capsys):
    assert cli.main([]) == 0
    assert "serve" in capsys.readouterr().out


def test_dashboard_server_uses_local_defaults(monkeypatch, capsys):
    import uvicorn

    calls = []
    monkeypatch.setenv("AGENTOS_DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setattr(uvicorn, "run", lambda app, **kwargs: calls.append((app, kwargs)))
    assert cli.main(["serve", "--port", "8765"]) == 0
    assert calls[0][1] == {"host": "127.0.0.1", "port": 8765}
    assert "http://127.0.0.1:8765" in capsys.readouterr().out


def test_invalid_server_token_reports_an_error_without_starting(monkeypatch, capsys):
    import uvicorn

    calls = []
    monkeypatch.setenv("AGENTOS_API_TOKEN", "short")
    monkeypatch.setattr(uvicorn, "run", lambda *args, **kwargs: calls.append(args))
    assert cli.main(["serve"]) == 1
    assert calls == []
    captured = capsys.readouterr()
    assert "at least 16 characters" in captured.err
    assert captured.out == ""
