import json

import httpx
import pytest
from fastapi.testclient import TestClient

from agent_engine import cli
from agent_engine.ai_planner import OpenAIPlanner, OpenAISettings
from agent_engine.api import Settings, create_app
from agent_engine.storage.repository import TaskRepository

TOKEN = "ai-integration-local-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
SECRET = "fake-provider-key-never-persist"
GOAL = "Combine two and three, then quadruple the answer."


@pytest.fixture
def repository():
    repository = TaskRepository("sqlite:///:memory:")
    yield repository
    repository.close()


def provider_response():
    steps = [
        {
            "tool_name": "add",
            "description": "Combine the values.",
            "tool_args_json": '{"a":2,"b":3}',
        },
        {
            "tool_name": "multiply",
            "description": "Quadruple the total.",
            "tool_args_json": '{"a":{"$ref":1},"b":4}',
        },
    ]
    return {
        "status": "completed",
        "output": [
            {
                "type": "message",
                "status": "completed",
                "role": "assistant",
                "content": [{"type": "output_text", "text": json.dumps({"steps": steps})}],
            }
        ],
    }


@pytest.fixture
def provider(monkeypatch, repository):
    calls = []
    monkeypatch.setenv("OPENAI_API_KEY", SECRET)
    monkeypatch.setenv("AGENTOS_MODEL", "test-structured-model")

    def handler(request):
        calls.append(request)
        pending = repository.list_tasks()[0]
        assert pending.status.value == "planning"
        assert pending.steps == []
        return httpx.Response(200, json=provider_response())

    configured = OpenAIPlanner(OpenAISettings.from_env(), transport=httpx.MockTransport(handler))
    monkeypatch.setattr(OpenAIPlanner, "from_env", classmethod(lambda cls: configured))
    return calls


def test_api_ai_plan_requires_each_approval_and_preserves_goal(repository, provider):
    with TestClient(create_app(Settings(api_token=TOKEN), repository)) as client:
        created = client.post(
            "/api/tasks",
            headers=AUTH,
            json={
                "goal": GOAL,
                "planner": "openai",
                "require_approval": False,
            },
        )
        assert created.status_code == 201
        task = created.json()
        assert task["goal"] == GOAL
        assert task["status"] == "waiting_for_approval"
        assert task["result"] is None
        assert all(step["attempts"] == 0 and step["requires_approval"] for step in task["steps"])
        for expected_status, expected_result in [
            ("waiting_for_approval", "5.0"),
            ("completed", "20.0"),
        ]:
            approved = client.post(
                f"/api/tasks/{task['task_id']}/approve",
                headers=AUTH,
                json={"revision": task["revision"]},
            )
            assert approved.status_code == 200
            task = approved.json()
            assert task["status"] == expected_status
            assert task["result"] == expected_result
        assert len(provider) == 1
        assert SECRET not in client.get("/api/tasks", headers=AUTH).text


def test_cli_ai_preview_and_saved_approvals(repository, provider, monkeypatch, capsys):
    monkeypatch.setattr(cli, "get_repository", lambda: repository)
    assert cli.main(["plan", GOAL, "--planner", "openai", "--json"]) == 0
    task = json.loads(capsys.readouterr().out)
    assert task["status"] == "pending"
    assert all(step["requires_approval"] for step in task["steps"])
    assert cli.main(["resume", task["task_id"], "--json"]) == 0
    task = json.loads(capsys.readouterr().out)
    assert task["status"] == "waiting_for_approval"
    for _ in range(2):
        assert cli.main(["approve", task["task_id"], "--json"]) == 0
        task = json.loads(capsys.readouterr().out)
    assert task["result"] == "20.0"
    assert len(provider) == 1


def test_explicit_local_mode_avoids_provider_even_when_server_defaults_to_ai(
    repository, provider, monkeypatch
):
    monkeypatch.setenv("AGENTOS_PLANNER", "openai")
    with TestClient(create_app(Settings(api_token=TOKEN), repository)) as client:
        task = client.post(
            "/api/tasks", headers=AUTH, json={"goal": "add 2 and 3", "planner": "local"}
        ).json()
        assert task["status"] == "completed"
        assert provider == []


def test_configuration_is_authenticated_and_never_exposes_key(repository, provider):
    with TestClient(create_app(Settings(api_token=TOKEN), repository)) as client:
        assert client.get("/api/planner").status_code == 401
        response = client.get("/api/planner", headers=AUTH)
        assert response.json()["default"] == "local"
        assert response.json()["openai_available"] is True
        assert response.json()["model"] == "test-structured-model"
        assert SECRET not in response.text
        assert provider == []


def test_unconfigured_ai_failure_is_saved_and_local_remains_available(repository):
    with TestClient(create_app(Settings(api_token=TOKEN), repository)) as client:
        assert client.get("/api/planner", headers=AUTH).json()["openai_available"] is False
        task = client.post(
            "/api/tasks", headers=AUTH, json={"goal": GOAL, "planner": "openai"}
        ).json()
        assert task["status"] == "failed"
        assert "OPENAI_API_KEY" in task["error"]
        local = client.post("/api/tasks", headers=AUTH, json={"goal": "add 2 and 3"}).json()
        assert local["status"] == "completed"
        assert (
            client.post(
                "/api/tasks", headers=AUTH, json={"goal": GOAL, "planner": "unknown"}
            ).status_code
            == 422
        )


def test_provider_failure_stays_out_of_task_history(repository, monkeypatch):
    requests = []

    def denied(request):
        requests.append(request)
        return httpx.Response(401, text=f"Internal debug secret {SECRET}")

    configured = OpenAIPlanner(
        OpenAISettings(api_key=SECRET, model="test-model"), transport=httpx.MockTransport(denied)
    )
    monkeypatch.setattr(OpenAIPlanner, "from_env", classmethod(lambda cls: configured))
    with TestClient(create_app(Settings(api_token=TOKEN), repository)) as client:
        task = client.post(
            "/api/tasks", headers=AUTH, json={"goal": GOAL, "planner": "openai"}
        ).json()
        assert task["status"] == "failed"
        assert "credentials" in task["error"]
        assert SECRET not in client.get("/api/tasks", headers=AUTH).text
        assert len(requests) == 1
