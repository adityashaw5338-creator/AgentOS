from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

from agent_engine.api import DEFAULT_CORS_ORIGINS, Settings, create_app
from agent_engine.storage.repository import TaskRepository

TOKEN = "cors-test-token-at-least-sixteen-characters"


@contextmanager
def cors_client(**settings):
    repository = TaskRepository("sqlite:///:memory:")
    try:
        with TestClient(
            create_app(Settings(api_token=TOKEN, **settings), repository=repository)
        ) as client:
            yield client
    finally:
        repository.close()


def preflight(client, origin, method="POST", headers="authorization,content-type"):
    return client.options(
        "/api/tasks",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": method,
            "Access-Control-Request-Headers": headers,
        },
    )


@pytest.mark.parametrize("origin", DEFAULT_CORS_ORIGINS)
def test_local_frontend_can_preflight_and_execute_authenticated_task(origin):
    with cors_client() as client:
        response = preflight(client, origin)
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == origin
        assert "authorization" in response.headers["access-control-allow-headers"].lower()
        assert "content-type" in response.headers["access-control-allow-headers"].lower()
        assert "access-control-allow-credentials" not in response.headers

        response = client.post(
            "/api/tasks",
            headers={"Origin": origin, "Authorization": f"Bearer {TOKEN}"},
            json={"goal": "calculate (2 + 3) * 4"},
        )
        assert response.status_code == 201
        assert response.headers["access-control-allow-origin"] == origin
        assert response.json()["status"] == "completed"
        assert float(response.json()["result"]) == 20


@pytest.mark.parametrize("authorization", [None, "Bearer incorrect", "Basic incorrect"])
def test_allowed_origin_does_not_bypass_authentication(authorization):
    origin = DEFAULT_CORS_ORIGINS[0]
    headers = {"Origin": origin}
    if authorization:
        headers["Authorization"] = authorization
    with cors_client() as client:
        response = client.post("/api/tasks", headers=headers, json={"goal": "add 2 and 3"})
        assert response.status_code == 401
        assert response.headers["access-control-allow-origin"] == origin
        assert response.headers["www-authenticate"] == "Bearer"
        history = client.get("/api/tasks", headers={"Authorization": f"Bearer {TOKEN}"})
        assert history.json()["total"] == 0


@pytest.mark.parametrize(
    "origin", ["https://unconfigured.example", "http://localhost:3001", "null"]
)
def test_unconfigured_origins_cannot_read_api_responses(origin):
    with cors_client() as client:
        response = preflight(client, origin)
        assert response.status_code == 400
        assert "access-control-allow-origin" not in response.headers
        response = client.get(
            "/api/tasks", headers={"Origin": origin, "Authorization": f"Bearer {TOKEN}"}
        )
        assert response.status_code == 200
        assert "access-control-allow-origin" not in response.headers


@pytest.mark.parametrize(
    ("method", "headers"), [("DELETE", "authorization"), ("POST", "x-unconfigured-header")]
)
def test_preflight_rejects_unconfigured_methods_and_headers(method, headers):
    with cors_client() as client:
        assert preflight(client, DEFAULT_CORS_ORIGINS[0], method, headers).status_code == 400


def test_configured_origin_replaces_development_defaults(monkeypatch):
    monkeypatch.setenv("AGENTOS_CORS_ORIGINS", " https://Frontend.Example:443/ , ")
    settings = Settings.from_env()
    assert settings.cors_origins == ("https://frontend.example",)
    with cors_client(cors_origins=settings.cors_origins) as client:
        assert preflight(client, "https://frontend.example").status_code == 200
        assert preflight(client, DEFAULT_CORS_ORIGINS[0]).status_code == 400


def test_environment_normalizes_and_deduplicates_browser_origins(monkeypatch):
    monkeypatch.setenv(
        "AGENTOS_CORS_ORIGINS",
        " https://Frontend.Example:443/, https://frontend.example, "
        "http://LOCALHOST:80/, http://localhost:5173/ , , http://[::1]:5173/ ",
    )
    assert Settings.from_env().cors_origins == (
        "https://frontend.example",
        "http://localhost",
        "http://localhost:5173",
        "http://[::1]:5173",
    )


def test_empty_environment_disables_cross_origin_access(monkeypatch):
    monkeypatch.setenv("AGENTOS_CORS_ORIGINS", " , ")
    settings = Settings.from_env()
    assert settings.cors_origins == ()
    with cors_client(cors_origins=settings.cors_origins) as client:
        assert preflight(client, DEFAULT_CORS_ORIGINS[0]).status_code == 400
        response = client.get("/api/tasks", headers={"Authorization": f"Bearer {TOKEN}"})
        assert response.status_code == 200


@pytest.mark.parametrize(
    "origin",
    [
        "",
        "*",
        "null",
        "localhost:3000",
        "ftp://frontend.example",
        "https:///frontend.example",
        "http://:3000",
        "http://frontend.example:",
        "http://frontend.example:invalid",
        "http://frontend.example:-1",
        "http://frontend.example:65536",
        "http://[::1",
        "http://[::1]:invalid",
        "http://[::1]extra:3000",
        "https://*.frontend.example",
        "https://user:password@frontend.example",
        "https://@frontend.example",
        "https://frontend.example/path",
        "https://frontend.example//",
        "https://frontend.example?query=value",
        "https://frontend.example?",
        "https://frontend.example#fragment",
        "https://frontend.example#",
        "https://front end.example",
        "https://front\tend.example",
        "https://front\nend.example",
        "https://front\x00end.example",
        "https://front\x7fend.example",
        "https://frontend.example\\path",
    ],
)
def test_invalid_origins_fail_at_configuration_time(origin):
    with pytest.raises(ValueError, match="CORS origins must"):
        Settings(cors_origins=(origin,))


@pytest.mark.parametrize("origin", ["http://localhost:0", "http://localhost:65535"])
def test_valid_port_boundaries_are_accepted(origin):
    assert Settings(cors_origins=(origin,)).cors_origins == (origin,)
