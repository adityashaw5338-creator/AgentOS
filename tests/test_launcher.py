import importlib.util
import socket
from pathlib import Path
from threading import Timer
from urllib.request import urlopen

import pytest


@pytest.fixture
def launcher():
    path = Path(__file__).resolve().parent.parent / "scripts/start-local.py"
    spec = importlib.util.spec_from_file_location("start_local", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_local_configuration_is_literal_and_scoped(launcher, tmp_path, monkeypatch):
    import os

    for name in ("OPENAI_API_KEY", "AGENTOS_MODEL", "AGENTOS_PLANNER"):
        monkeypatch.setenv(name, "inherited")
    original_path = os.environ["PATH"]
    configuration = tmp_path / "settings.env"
    configuration.write_text(
        '# comments and blanks are allowed\n\nOPENAI_API_KEY="fake&%!$()#secret"\n'
        "export AGENTOS_MODEL='openrouter/free'\nAGENTOS_PLANNER=openai\n"
        "PATH=must-not-change\n",
        encoding="utf-8",
    )
    launcher.environment(configuration)
    assert os.environ["OPENAI_API_KEY"] == "fake&%!$()#secret"
    assert os.environ["AGENTOS_MODEL"] == "openrouter/free"
    assert os.environ["AGENTOS_PLANNER"] == "openai"
    assert os.environ["PATH"] == original_path


def test_invalid_file_does_not_partially_load_or_disclose_values(launcher, tmp_path, monkeypatch):
    import os

    monkeypatch.setenv("AGENTOS_MODEL", "original")
    configuration = tmp_path / "settings.env"
    configuration.write_text('AGENTOS_MODEL=changed\nOPENAI_API_KEY="private-value\n')
    with pytest.raises(ValueError) as error:
        launcher.environment(configuration)
    assert "private-value" not in str(error.value)
    assert os.environ["AGENTOS_MODEL"] == "original"


def test_busy_port_cannot_open_an_unrelated_service(launcher, monkeypatch, capsys):
    monkeypatch.setenv("AGENTOS_API_TOKEN", "launcher-test-operator-token")
    monkeypatch.setenv("AGENTOS_DATABASE_URL", "sqlite:///:memory:")
    opened = []
    monkeypatch.setattr(launcher.webbrowser, "open", lambda *args, **kwargs: opened.append(args))
    with socket.socket() as occupied:
        occupied.bind(("127.0.0.1", 0))
        occupied.listen(1)
        assert launcher.serve(occupied.getsockname()[1], True) == 1
    output = capsys.readouterr()
    assert "port" in output.err
    assert "launcher-test-operator-token" not in output.out + output.err
    assert opened == []


def test_browser_opens_only_when_the_new_server_can_respond(launcher, monkeypatch):
    import uvicorn

    monkeypatch.setenv("AGENTOS_API_TOKEN", "launcher-test-operator-token")
    monkeypatch.setenv("AGENTOS_DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("AGENTOS_ALLOWED_HOSTS", "127.0.0.1")
    observed = []
    running = []
    original_run = uvicorn.Server.run

    def run(server, **kwargs):
        running.append(server)
        guard = Timer(5, lambda: setattr(server, "should_exit", True))
        guard.daemon = True
        guard.start()
        try:
            return original_run(server, **kwargs)
        finally:
            guard.cancel()

    def browser(url, **kwargs):
        try:
            with urlopen(url + "/api/health", timeout=2) as response:
                observed.append(response.status)
            return True
        finally:
            running[0].should_exit = True

    monkeypatch.setattr(uvicorn.Server, "run", run)
    monkeypatch.setattr(launcher.webbrowser, "open", browser)
    assert launcher.serve(0, True) == 0
    assert observed == [200]
