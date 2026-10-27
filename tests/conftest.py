import pytest


@pytest.fixture(autouse=True)
def isolate_ai_configuration(monkeypatch):
    """The suite never inherits a developer's provider settings or spends API credits."""
    for name in (
        "AGENTOS_PLANNER",
        "OPENAI_API_KEY",
        "AGENTOS_MODEL",
        "OPENAI_BASE_URL",
        "AGENTOS_AI_TIMEOUT",
    ):
        monkeypatch.delenv(name, raising=False)
