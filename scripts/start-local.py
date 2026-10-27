"""Launch this checkout from Windows Explorer, with private local configuration."""

from __future__ import annotations

import argparse
import os
import re
import socket
import subprocess
import sys
import webbrowser
from pathlib import Path
from threading import Thread

ROOT = Path(__file__).resolve().parent.parent


def environment(path: Path) -> None:
    """Read supported settings literally; never evaluate shell code or print values."""
    if not path.is_file():
        return
    settings = {}
    for number, raw in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        name, separator, value = line.partition("=")
        name, value = name.strip(), value.strip()
        if not separator or not re.fullmatch(r"[A-Z_][A-Z0-9_]*", name):
            raise ValueError(f"Invalid configuration on line {number} of the environment file.")
        if value[:1] in {"'", '"'}:
            if len(value) < 2 or value[-1] != value[0]:
                raise ValueError(f"Unclosed quote on line {number} of the environment file.")
            value = value[1:-1]
        if name.startswith("AGENTOS_") or name in {"OPENAI_API_KEY", "OPENAI_BASE_URL"}:
            settings[name] = value
    # This launcher uses the project's configuration, scoped to this process.
    os.environ.update(settings)


def prepare() -> int | None:
    """Bootstrap only when needed, before loading any provider credentials."""
    if sys.version_info < (3, 11):
        print(
            "Python 3.11 or newer is required. Install a current Python version.", file=sys.stderr
        )
        return 1
    venv = ROOT / ".venv"
    python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if Path(sys.prefix).resolve() != venv.resolve():
        if not python.is_file():
            print("Setting up AgentOS for the first time...", flush=True)
            subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True, cwd=ROOT)
        return subprocess.call(
            [str(python), str(Path(__file__).resolve()), *sys.argv[1:]], cwd=ROOT
        )
    ready = subprocess.run(
        [sys.executable, "-c", "import agent_engine.api, agent_engine.ai_planner, uvicorn"],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if ready.returncode:
        print(
            "Installing AgentOS dependencies. An internet connection is needed once...", flush=True
        )
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "-e",
                str(ROOT),
            ],
            check=True,
            cwd=ROOT,
        )
    return None


def serve(port: int, open_browser: bool) -> int:
    import uvicorn

    from agent_engine.api import Settings, create_app

    settings = Settings.from_env()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        if os.name == "nt":
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            listener.bind(("127.0.0.1", port))
            listener.listen(128)
        except OSError:
            print(
                f"Cannot listen on port {port}. Close the other server or run start.bat --port 8001.",
                file=sys.stderr,
            )
            return 1
        actual_port = listener.getsockname()[1]
        url = f"http://127.0.0.1:{actual_port}"
        app = create_app(settings=settings)

        def browse() -> None:
            try:
                if not webbrowser.open(url, new=2):
                    print(f"Open {url} in your browser.", flush=True)
            except Exception:
                print(f"Open {url} in your browser.", flush=True)

        class LocalServer(uvicorn.Server):
            async def startup(self, sockets=None):
                await super().startup(sockets=sockets)
                if self.started and open_browser:
                    Thread(target=browse, daemon=True).start()

        print(
            f"\nAgentOS\nDashboard: {url}\nAccess token: {settings.api_token}\n\n"
            "Paste the access token into the dashboard to connect.\n"
            "Keep this window open while using AgentOS. Press Ctrl+C to stop.\n",
            flush=True,
        )
        server = LocalServer(
            uvicorn.Config(app, host="127.0.0.1", port=actual_port, access_log=False)
        )
        server.run(sockets=[listener])
        if not server.started:
            print(
                "AgentOS stopped before startup completed. Check the message above.",
                file=sys.stderr,
            )
            return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Start the local AgentOS dashboard.")
    parser.add_argument(
        "--port", type=int, default=8000, help="Local port; 0 selects an unused port."
    )
    parser.add_argument(
        "--no-browser", action="store_true", help="Start without opening a browser."
    )
    parser.add_argument("--env-file", type=Path, help="Override the default project .env file.")
    args = parser.parse_args()
    if not 0 <= args.port <= 65535:
        parser.error("Port must be between 0 and 65535.")
    try:
        prepared = prepare()
        if prepared is not None:
            return prepared
        sys.path.insert(0, str(ROOT))
        if args.env_file and not args.env_file.is_file():
            raise ValueError("The specified environment file was not found.")
        environment(args.env_file.resolve() if args.env_file else ROOT / ".env")
        return serve(args.port, not args.no_browser)
    except KeyboardInterrupt:
        print("\nAgentOS stopped.")
        return 0
    except ValueError as error:
        print(f"AgentOS could not start: {error}", file=sys.stderr)
        return 1
    except Exception as error:
        print(
            f"AgentOS could not start ({type(error).__name__}). Check Python and your .env settings.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
