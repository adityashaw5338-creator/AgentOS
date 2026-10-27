import json

import httpx
import pytest
from pydantic import BaseModel

from agent_engine import ai_planner
from agent_engine.agent import build_registry
from agent_engine.executor import approve_current_step, execute_plan
from agent_engine.planner import create_plan, planner_info
from agent_engine.state import AgentState, AgentStatus
from agent_engine.tools.registry import ToolRegistry


@pytest.fixture(autouse=True)
def clean_provider_environment(monkeypatch):
    for name in (
        "AGENTOS_PLANNER",
        "OPENAI_API_KEY",
        "AGENTOS_MODEL",
        "OPENAI_BASE_URL",
        "AGENTOS_AI_TIMEOUT",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def settings():
    return ai_planner.OpenAISettings(api_key="test-secret-never-log", model="test-model")


def step(name="add", args=None, **extra):
    return {
        "tool_name": name,
        "description": f"Apply {name}.",
        "tool_args_json": json.dumps({"a": 2, "b": 3} if args is None else args),
        **extra,
    }


def response(plan=None):
    return {
        "status": "completed",
        "output": [
            {
                "type": "message",
                "status": "completed",
                "role": "assistant",
                "content": [
                    {
                        "type": "output_text",
                        "text": json.dumps({"steps": [step()]} if plan is None else plan),
                    }
                ],
            }
        ],
    }


def planner(settings, payload=None, *, status=200, handler=None):
    transport = httpx.MockTransport(
        handler
        or (lambda request: httpx.Response(status, json=response() if payload is None else payload))
    )
    return ai_planner.OpenAIPlanner(settings, transport=transport)


def test_responses_request_and_local_approval_contract(settings):
    requests = []
    payload = response({"steps": [step(), step("multiply", {"a": {"$ref": 1}, "b": 4})]})

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=payload)

    registry = build_registry()
    state = AgentState(goal="Combine two and three, then quadruple the answer.")
    planner(settings, handler=handler).create_plan(state, registry)
    assert len(requests) == 1
    request = requests[0]
    assert request.url == "https://api.openai.com/v1/responses"
    assert request.headers["authorization"] == f"Bearer {settings.api_key}"
    body = json.loads(request.content)
    assert body["model"] == settings.model
    assert body["input"] == [{"role": "user", "content": state.goal}]
    assert body["store"] is False
    assert body["max_output_tokens"] == ai_planner.MAX_OUTPUT_TOKENS
    assert body["text"]["format"]["type"] == "json_schema"
    assert body["text"]["format"]["strict"] is True
    assert "tools" not in body  # The provider proposes data; it cannot call tools.
    assert settings.api_key not in request.content.decode()
    assert "multiply" in body["instructions"]
    assert all(value > 0 for value in request.extensions["timeout"].values())
    assert state.status == AgentStatus.PENDING
    assert all(item.requires_approval and not item.approved for item in state.steps)
    execute_plan(state, registry)
    assert state.status == AgentStatus.WAITING_FOR_APPROVAL
    assert state.current_step == 0
    approve_current_step(state)
    execute_plan(state, registry)
    assert state.status == AgentStatus.WAITING_FOR_APPROVAL
    assert state.current_step == 1
    approve_current_step(state)
    execute_plan(state, registry)
    assert state.status == AgentStatus.COMPLETED
    assert state.result == "20.0"


def test_custom_typed_tool_is_validated_without_executing(settings):
    class Payload(BaseModel):
        text: str

    calls = []

    def uppercase(payload: Payload) -> str:
        calls.append(payload)
        return payload.text.upper()

    registry = ToolRegistry()
    registry.register("uppercase", uppercase)
    state = AgentState(goal="Uppercase the text hello.")
    planner(
        settings, response({"steps": [step("uppercase", {"payload": {"text": "hello"}})]})
    ).create_plan(state, registry)
    assert calls == []
    assert state.steps[0].tool_args == {"payload": {"text": "hello"}}
    execute_plan(state, registry)
    approve_current_step(state)
    execute_plan(state, registry)
    assert state.result == "HELLO"
    assert isinstance(calls[0], Payload)


def test_local_default_never_uses_api_even_when_a_key_is_present(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "a-valid-test-key")
    monkeypatch.setenv("AGENTOS_MODEL", "test-model")
    monkeypatch.setattr(
        ai_planner.OpenAIPlanner, "from_env", lambda: pytest.fail("Unexpected AI call")
    )
    state = create_plan(AgentState(goal="add 2 and 3"))
    assert not state.steps[0].requires_approval
    with pytest.raises(ValueError, match="supports arithmetic"):
        create_plan(AgentState(goal="What is the total for a few things?"))


def test_explicit_openai_mode_routes_and_local_override_does_not(monkeypatch, settings):
    instance = planner(settings)
    monkeypatch.setattr(ai_planner.OpenAIPlanner, "from_env", lambda: instance)
    assert (
        create_plan(AgentState(goal="Sum these values"), mode="openai").steps[0].requires_approval
    )
    monkeypatch.setenv("AGENTOS_PLANNER", "openai")
    assert create_plan(AgentState(goal="Sum these values")).steps[0].requires_approval
    assert not create_plan(AgentState(goal="2 + 3"), mode="local").steps[0].requires_approval


def test_unknown_mode_does_not_silently_fallback(monkeypatch):
    monkeypatch.setenv("AGENTOS_PLANNER", "invalid-mode")
    with pytest.raises(ValueError, match="AGENTOS_PLANNER"):
        create_plan(AgentState(goal="2 + 3"))
    assert create_plan(AgentState(goal="2 + 3"), mode="local").steps
    metadata = planner_info()
    assert metadata["default"] is None
    assert "AGENTOS_PLANNER" in metadata["message"]


def test_provider_info_validates_config_without_network(monkeypatch):
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: pytest.fail("Unexpected network client"))
    metadata = planner_info()
    assert metadata["default"] == "local"
    assert metadata["openai_available"] is False
    assert "OPENAI_API_KEY" in metadata["message"]
    monkeypatch.setenv("OPENAI_API_KEY", "provider-secret")
    monkeypatch.setenv("AGENTOS_MODEL", "chosen-model")
    monkeypatch.setenv("AGENTOS_PLANNER", "openai")
    assert planner_info() == {
        "default": "openai",
        "openai_available": True,
        "model": "chosen-model",
        "timeout_seconds": 20.0,
        "message": None,
    }
    assert "provider-secret" not in json.dumps(planner_info())


@pytest.mark.parametrize(
    "updates",
    [
        {"api_key": ""},
        {"api_key": "bad\nkey"},
        {"model": ""},
        {"model": "bad\nmodel"},
        {"timeout": 0},
        {"timeout": True},
        {"timeout": float("nan")},
        {"timeout": 121},
        {"base_url": "http://api.example/v1"},
        {"base_url": "ftp://localhost/v1"},
        {"base_url": "https://user:secret@example.com/v1"},
        {"base_url": "https://@example.com/v1"},
        {"base_url": "https://example.com:abc/v1"},
        {"base_url": "https://example.com:65536/v1"},
        {"base_url": "https://example.com:/v1"},
        {"base_url": "https://example.com/v1?key=secret"},
        {"base_url": "https://example.com/v1#fragment"},
        {"base_url": "https://example.com/v1#"},
        {"base_url": "https://example.com/v1?"},
        {"base_url": "https://bad\\host/v1"},
        {"base_url": "https://bad host/v1"},
        {"base_url": "http://localhost.evil.example/v1"},
        {"base_url": "https:///v1"},
    ],
)
def test_invalid_provider_configuration_is_rejected_without_echoing_secrets(updates):
    with pytest.raises(ValueError) as error:
        ai_planner.OpenAISettings(**{"api_key": "secret", "model": "model", **updates})
    assert "secret" not in str(error.value)


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/custom/v1/",
        "http://localhost:11434/v1/",
        "http://127.0.0.1:8001/v1",
        "http://[::1]:8001/v1",
    ],
)
def test_custom_api_endpoints_and_loopback_are_supported(url):
    settings = ai_planner.OpenAISettings(api_key="test-key", model="model", base_url=url)
    assert settings.base_url == url.rstrip("/")
    assert "test-key" not in repr(settings)


def test_configurable_timeout_and_model_are_loaded_from_environment(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("AGENTOS_MODEL", "chosen-model")
    monkeypatch.setenv("AGENTOS_AI_TIMEOUT", "12.5")
    assert ai_planner.OpenAISettings.from_env().timeout == 12.5
    monkeypatch.setenv("AGENTOS_AI_TIMEOUT", "not-a-number")
    with pytest.raises(ValueError, match="AGENTOS_AI_TIMEOUT"):
        ai_planner.OpenAISettings.from_env()


@pytest.mark.parametrize(
    "bad_plan",
    [
        {"steps": []},
        {"steps": [step()] * 33},
        {"steps": [step()], "approved": True},
        {"steps": [step("not_a_tool")]},
        {"steps": [step(approved=True)]},
        {"steps": [step(completed=True)]},
        {"steps": [step(requires_approval=False)]},
        {"steps": [step(step_id=42)]},
        {"steps": [step(args={"a": {"$ref": 1}, "b": 3})]},
        {"steps": [step(args={"a": {"$ref": 2}, "b": 3})]},
        {"steps": [step(args={"a": True, "b": 3})]},
        {"steps": [step(args={"a": 1, "b": 3, "extra": 4})]},
        {"steps": [step(args={"a": 1})]},
        {"steps": [step(args=[])]},
        {"steps": [step(args={"a": float("nan"), "b": 3})]},
        {"steps": [step(args={"a": float("inf"), "b": 3})]},
        {"steps": [step(tool_args_json='{"a": 1, "a": 2, "b": 3}')]},
        {"steps": [step(tool_args_json='{"a": 1e999, "b": 3}')]},
        {"steps": [step(description="")]},
        {"steps": [step(description=None)]},
        {"steps": [step(description="x" * 4001)]},
        {"steps": [step(tool_args_json={"a": 1, "b": 2})]},
    ],
)
def test_untrusted_model_plans_are_rejected_before_any_state_is_installed(settings, bad_plan):
    state = AgentState(goal="User goal")
    with pytest.raises(ValueError, match="not a valid plan"):
        planner(settings, response(bad_plan)).create_plan(state, build_registry())
    assert state.steps == []
    assert state.goal == "User goal"
    assert state.execution_log == []


@pytest.mark.parametrize("status", [301, 307, 400, 401, 403, 429, 500, 503])
def test_provider_errors_do_not_leak_body_or_retry(settings, status):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            status,
            json={"error": {"message": settings.api_key}},
            headers={"Location": "https://redirect.example/responses"},
        )

    with pytest.raises(ValueError) as error:
        planner(settings, handler=handler).create_plan(AgentState(goal="sum"), build_registry())
    assert settings.api_key not in str(error.value)
    assert len(calls) == 1


@pytest.mark.parametrize(
    "error_type", [httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError]
)
def test_transport_failures_are_sanitized(settings, error_type):
    def handler(request):
        raise error_type(f"private upstream error {settings.api_key}", request=request)

    with pytest.raises(ValueError) as error:
        planner(settings, handler=handler).create_plan(AgentState(goal="sum"), build_registry())
    assert settings.api_key not in str(error.value)
    assert "private upstream" not in str(error.value)


@pytest.mark.parametrize(
    "payload",
    [
        {"status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"}},
        {"status": "failed", "error": {"message": "test-secret-never-log"}},
        {"status": "completed", "output": []},
        {"status": "completed", "output": [{"type": "function_call", "name": "add"}]},
        {"status": "completed", "output": [{"type": "message", "status": "in_progress"}]},
        [],
        None,
    ],
)
def test_incomplete_or_unexpected_responses_are_not_accepted(settings, payload):
    with pytest.raises(ValueError) as error:
        planner(settings, handler=lambda request: httpx.Response(200, json=payload)).create_plan(
            AgentState(goal="sum"), build_registry()
        )
    assert settings.api_key not in str(error.value)


def test_refusal_and_reasoning_are_handled(settings):
    refused = response()
    refused["output"][0]["content"] = [{"type": "refusal", "refusal": settings.api_key}]
    with pytest.raises(ValueError, match="declined") as error:
        planner(settings, refused).create_plan(AgentState(goal="sum"), build_registry())
    assert settings.api_key not in str(error.value)
    valid = response()
    valid["output"].insert(0, {"type": "reasoning", "summary": []})
    assert planner(settings, valid).create_plan(AgentState(goal="sum"), build_registry()).steps


@pytest.mark.parametrize(
    "raw", [b"not-json-secret", b"\xff", b'{"status":"completed", "status":"failed"}']
)
def test_invalid_provider_json_is_sanitized(settings, raw):
    with pytest.raises(ValueError, match="invalid JSON"):
        planner(settings, handler=lambda request: httpx.Response(200, content=raw)).create_plan(
            AgentState(goal="sum"), build_registry()
        )


def test_response_and_plan_size_are_bounded(settings):
    with pytest.raises(ValueError, match="response exceeded"):
        planner(
            settings,
            handler=lambda request: httpx.Response(
                200, content=b"x" * (ai_planner.MAX_RESPONSE_BYTES + 1)
            ),
        ).create_plan(AgentState(goal="sum"), build_registry())
    payload = response()
    payload["output"][0]["content"][0]["text"] = "x" * (ai_planner.MAX_PLAN_BYTES + 1)
    with pytest.raises(ValueError, match="plan exceeded"):
        planner(settings, payload).create_plan(AgentState(goal="sum"), build_registry())


def test_slow_stream_cannot_extend_planning_indefinitely(monkeypatch, settings):
    clock = [0.0]
    monkeypatch.setattr(ai_planner.time, "monotonic", lambda: clock[0])

    class SlowStream(httpx.SyncByteStream):
        def __iter__(self):
            clock[0] = settings.timeout + 1
            yield json.dumps(response()).encode()

    with pytest.raises(ValueError, match="timed out"):
        planner(
            settings, handler=lambda request: httpx.Response(200, stream=SlowStream())
        ).create_plan(AgentState(goal="sum"), build_registry())


def test_multiple_messages_and_invalid_unicode_are_rejected(settings):
    payload = response()
    payload["output"] *= 2
    with pytest.raises(ValueError, match="single complete plan"):
        planner(settings, payload).create_plan(AgentState(goal="sum"), build_registry())
    payload = response()
    payload["output"][0]["content"][0]["text"] = "\ud800"
    with pytest.raises(ValueError, match="invalid plan text"):
        planner(
            settings,
            handler=lambda request: httpx.Response(200, content=json.dumps(payload).encode()),
        ).create_plan(AgentState(goal="sum"), build_registry())


def test_no_network_for_empty_goal_or_empty_registry(settings):
    instance = planner(settings, handler=lambda request: pytest.fail("Unexpected HTTP request"))
    with pytest.raises(ValueError, match="cannot be empty"):
        instance.create_plan(AgentState(goal="   "), build_registry())
    with pytest.raises(ValueError, match="at least one tool"):
        instance.create_plan(AgentState(goal="goal"), ToolRegistry())
