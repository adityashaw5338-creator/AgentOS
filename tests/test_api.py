from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from agent_engine.api import Settings, create_app
from agent_engine.storage.repository import TaskRepository
from agent_engine.tools.registry import ToolRegistry

TOKEN = "test-token-at-least-sixteen-characters"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def client():
    repository = TaskRepository("sqlite:///:memory:")
    with TestClient(create_app(Settings(api_token=TOKEN), repository=repository)) as client:
        yield client
    repository.close()


def post_task(client, goal="calculate (2 + 3) * 4", **options):
    response = client.post("/api/tasks", headers=AUTH, json={"goal": goal, **options})
    assert response.status_code == 201, response.text
    return response.json()


def action(client, task, name):
    return client.post(
        f"/api/tasks/{task['task_id']}/{name}", headers=AUTH, json={"revision": task["revision"]}
    )


def test_health_is_public_but_history_and_schema_require_auth(client):
    assert client.get("/api/health").json()["status"] == "ok"
    for route in ("/api/tasks", "/api/stats", "/api/tools", "/api/openapi.json"):
        assert client.get(route).status_code == 401
        assert client.get(route, headers={"Authorization": "Bearer incorrect"}).status_code == 401
    assert client.post("/api/tasks", json={"goal": "add 2 and 3"}).status_code == 401
    assert client.get("/api/tools", headers=AUTH).json()["tools"][0]["parameters"]


def test_unsupported_auth_scheme_is_rejected_with_challenge(client):
    response = client.get("/api/tasks", headers={"Authorization": "Basic wrong"})
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_task_execution_and_history(client):
    task = post_task(client)
    assert task["status"] == "completed"
    assert float(task["result"]) == 20
    history = client.get("/api/tasks", headers=AUTH).json()
    assert history["total"] == 1
    assert history["tasks"][0] == task
    assert client.get(f"/api/tasks/{task['task_id']}", headers=AUTH).json() == task
    assert client.get("/api/stats", headers=AUTH).json()["completed"] == 1


def test_plan_preview_can_be_executed_once(client):
    pending = post_task(client, execute=False)
    assert pending["status"] == "pending"
    assert pending["steps"][0]["attempts"] == 0
    response = action(client, pending, "execute")
    assert response.status_code == 200
    completed = response.json()
    assert completed["status"] == "completed"
    assert completed["revision"] > pending["revision"]
    assert action(client, pending, "execute").status_code == 409
    assert action(client, completed, "execute").status_code == 409


def test_each_approval_only_releases_current_step(client):
    waiting = post_task(client, require_approval=True)
    assert waiting["status"] == "waiting_for_approval"
    assert all(step["attempts"] == 0 for step in waiting["steps"])
    next_waiting = action(client, waiting, "approve").json()
    assert next_waiting["status"] == "waiting_for_approval"
    assert next_waiting["current_step"] == 1
    assert next_waiting["steps"][0]["attempts"] == 1
    completed = action(client, next_waiting, "approve").json()
    assert completed["status"] == "completed"
    assert [step["attempts"] for step in completed["steps"]] == [1, 1]


def test_cancelled_task_cannot_run(client):
    pending = post_task(client, execute=False)
    cancelled = action(client, pending, "cancel").json()
    assert cancelled["status"] == "cancelled"
    assert action(client, cancelled, "execute").status_code == 409
    assert action(client, cancelled, "approve").status_code == 409
    assert action(client, post_task(client), "cancel").status_code == 409


def test_failed_goal_is_persisted_with_honest_error(client):
    failed = post_task(client, "research the web")
    assert failed["status"] == "failed"
    assert "supports arithmetic" in failed["error"]
    divide = post_task(client, "divide 10 by 0")
    assert divide["status"] == "failed"
    assert divide["steps"][0]["attempts"] == 1


@pytest.mark.parametrize(
    "body",
    [
        {"goal": " "},
        {"goal": "x" * 4001},
        {"goal": "add 2 and 3", "execute": "false"},
        {"goal": "add 2 and 3", "unknown": True},
        {"goal": 42},
    ],
)
def test_invalid_task_inputs_rejected_before_execution(client, body):
    assert client.post("/api/tasks", headers=AUTH, json=body).status_code == 422
    assert client.get("/api/stats", headers=AUTH).json()["total"] == 0


def test_invalid_actions_and_filters(client):
    assert client.get("/api/tasks/missing", headers=AUTH).status_code == 404
    pending = post_task(client, execute=False)
    assert action(client, pending, "approve").status_code == 409
    assert (
        client.post(
            f"/api/tasks/{pending['task_id']}/execute", headers=AUTH, json={"revision": True}
        ).status_code
        == 422
    )
    for query in ("limit=0", "offset=-1", "status=unknown"):
        assert client.get(f"/api/tasks?{query}", headers=AUTH).status_code == 422


def test_literal_search_and_pagination(client):
    post_task(client, "100% unsupported")
    post_task(client, "1000 unsupported")
    assert client.get("/api/tasks", headers=AUTH, params={"search": "100%"}).json()["total"] == 1
    page = client.get("/api/tasks", headers=AUTH, params={"limit": 1, "offset": 1}).json()
    assert page["total"] == 2
    assert len(page["tasks"]) == 1


def test_security_headers_and_untrusted_host(client):
    response = client.get("/api/health")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
    assert response.headers["Cache-Control"] == "no-store"
    assert client.get("/api/health", headers={"Host": "untrusted.example"}).status_code == 400


def test_registry_approval_cannot_be_disabled_by_client():
    effects = []

    def sensitive(text: str) -> str:
        effects.append(text)
        return text

    registry = ToolRegistry()
    registry.register("sensitive", sensitive, requires_approval=True)
    repository = TaskRepository("sqlite:///:memory:")
    with TestClient(create_app(Settings(api_token=TOKEN), repository, registry)) as client:
        goal = '{"steps":[{"tool_name":"sensitive","tool_args":{"text":"yes"},"requires_approval":false}]}'
        waiting = post_task(client, goal)
        assert not effects
        assert waiting["status"] == "waiting_for_approval"
        assert action(client, waiting, "approve").json()["status"] == "completed"
        assert effects == ["yes"]
    repository.close()


def test_two_api_instances_cannot_execute_same_side_effect(tmp_path):
    effects = []

    def record(text: str) -> str:
        effects.append(text)
        return text

    registry = ToolRegistry()
    registry.register("record", record)
    url = f"sqlite:///{(tmp_path / 'shared.db').as_posix()}"
    repos = [TaskRepository(url), TaskRepository(url)]
    apps = [create_app(Settings(api_token=TOKEN), repo, registry) for repo in repos]
    with TestClient(apps[0]) as first, TestClient(apps[1]) as second:
        pending = post_task(
            first, '{"steps":[{"tool_name":"record","tool_args":{"text":"once"}}]}', execute=False
        )
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(
                executor.map(lambda c: action(c, pending, "execute").status_code, [first, second])
            )
        assert sorted(results) == [200, 409]
        assert effects == ["once"]
    for repo in repos:
        repo.close()
