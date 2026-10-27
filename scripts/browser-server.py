"""Start the browser checks against this checkout and an in-memory database only."""

import json
import os
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> None:
    # Also isolate direct invocation of this helper from a developer's provider settings.
    os.environ["AGENTOS_PLANNER"] = "local"
    for name in ("OPENAI_API_KEY", "AGENTOS_MODEL", "OPENAI_BASE_URL", "AGENTOS_AI_TIMEOUT"):
        os.environ.pop(name, None)

    import uvicorn

    import agent_engine
    from agent_engine.api import Settings, create_app

    source = Path(agent_engine.__file__).resolve()
    expected = ROOT / "agent_engine" / "__init__.py"
    if source != expected:
        raise RuntimeError(f"Expected source {expected}; imported {source}.")
    settings = Settings(
        api_token=os.environ["AGENTOS_TEST_TOKEN"],
        database_url="sqlite:///:memory:",
        allowed_hosts=("127.0.0.1",),
    )
    app = create_app(settings=settings)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(128)
        port = listener.getsockname()[1]
        print(
            "AGENTOS_BROWSER_SERVER "
            + json.dumps({"url": f"http://127.0.0.1:{port}", "source": str(source)}),
            flush=True,
        )
        server = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", access_log=False)
        )
        server.run(sockets=[listener])


if __name__ == "__main__":
    main()
