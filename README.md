# AgentOS

A modular Python agent engine with validated tools, persistent task history, a protected
API, and a local dashboard.

The built-in planner supports arithmetic requests and explicit JSON tool plans, with
no API key required. The dashboard and CLI share persisted task history.

## Quick start

Requires Python 3.11 or newer; Python 3.12 is recommended. Clone the repository or
download and extract its source archive, then open the project directory.

```powershell
git clone https://github.com/adityashaw5338-creator/AgentOS.git
cd AgentOS
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\agentos.exe serve
```

On macOS/Linux, use `python3`, `.venv/bin/python`, and `.venv/bin/agentos`.

Open **http://127.0.0.1:8000** and enter the access token printed in the terminal.
The token changes on each start unless AGENTOS_API_TOKEN is configured. Stop with Ctrl+C.

The dashboard supports task creation, plan previews, step arguments, results, execution
logs, approvals, cancellation, history search, pagination, and a tool catalog.
History starts empty. All displayed tasks come from the database. Fonts are bundled.

## CLI examples

```powershell
.\.venv\Scripts\agentos.exe run "add 2 and 3"
.\.venv\Scripts\agentos.exe run "subtract 2 from 10"
.\.venv\Scripts\agentos.exe run "calculate (2 + 3) * 4"
.\.venv\Scripts\agentos.exe plan "divide 10 by 2"
.\.venv\Scripts\agentos.exe history
.\.venv\Scripts\agentos.exe history --limit 25 --offset 25
.\.venv\Scripts\agentos.exe show TASK_ID
.\.venv\Scripts\agentos.exe resume TASK_ID
.\.venv\Scripts\agentos.exe run --require-approval "calculate (2 + 3) * 4"
.\.venv\Scripts\agentos.exe approve TASK_ID
.\.venv\Scripts\agentos.exe cancel TASK_ID
.\.venv\Scripts\agentos.exe tools --json
```

Legacy entry points work: `python -m agent_engine.cli "add 2 and 3"` and
`python cli.py history`. Use --help for options. Failed tasks return a nonzero CLI exit
code and remain in history.

In the dashboard, enter a goal and choose Run task or Preview plan. Enable Require approval
to pause before every tool call. Approving releases only the current step. Pending and
waiting tasks can be cancelled. The CLI and dashboard share history with the same database.

## Engine behavior

- Planning compiles anchored arithmetic requests or a bounded AST into actual tool calls.
- Pydantic validates typed tool arguments, rejects unexpected fields, and generates schemas.
- Execution resolves prior results, records outputs and attempts, and enforces approval gates.
- ValueError is permanent; other tool exceptions may be retried, with bounded attempts.
- SQLAlchemy stores complete task snapshots and uses optimistic revisions for updates.
- Resuming clients claim a task before execution to avoid simultaneous duplicate tool calls.
- Bearer tokens protect task data and actions. The dashboard keeps its token in memory.

Built-in tools are add, subtract, multiply, divide, and power. Goals are limited to
4,000 characters and plans to 32 steps. Calculator values must be finite real numbers
with magnitude at most 1e100; exponents are bounded.

Arbitrary Python, shell commands, file access, and web research are not built-in tools.
The planner is deterministic. A configured AI provider and a broader tool catalog are
future extensions.

## Explicit plans and custom tools

Enter a JSON object as the goal:

```json
{
  "steps": [
    {"step_id": 1, "tool_name": "add", "tool_args": {"a": 2, "b": 3}},
    {
      "step_id": 2,
      "tool_name": "multiply",
      "tool_args": {"a": {"$ref": 1}, "b": 4},
      "requires_approval": true
    }
  ]
}
```

A $ref points to the integer ID of a previous step. The executor resolves its typed
result before validating the receiving tool. Plans cannot supply approval or completion
state. A registry approval requirement cannot be disabled by a plan.

```python
from agent_engine.agent import run_agent
from agent_engine.tools.registry import ToolRegistry

def uppercase(text: str) -> str:
    return text.upper()

registry = ToolRegistry()
registry.register("uppercase", uppercase, "Uppercase text.", requires_approval=True)
state = run_agent(
    '{"steps":[{"tool_name":"uppercase","tool_args":{"text":"hello"}}]}',
    registry=registry,
)
assert state.status.value == "waiting_for_approval"
```

Custom tools need typed keyword arguments and JSON-serializable results.
Validated arguments reach the callable as their declared Python types, including nested
Pydantic models. Saved plans retain serializable arguments across approval pauses.
Use `create_app(repository=..., registry=...)` to serve a custom registry.
Retried tools should be idempotent or implement idempotency keys; persistence cannot
guarantee exactly-once external side effects.

## API

All `/api` routes except GET /api/health require `Authorization: Bearer YOUR_TOKEN`.
The dashboard shell and bundled static assets are public; task data and actions are protected.

| Route | Behavior |
| --- | --- |
| GET /api/health | Health and version |
| GET /api/tools | Tool definitions and schemas |
| GET /api/stats | Counts by task state |
| GET /api/tasks | History; limit, offset, status, search |
| GET /api/tasks/{id} | Task snapshot |
| POST /api/tasks | Create a task |
| POST /api/tasks/{id}/execute | Execute a pending preview |
| POST /api/tasks/{id}/approve | Approve the current waiting step and continue |
| POST /api/tasks/{id}/cancel | Cancel a pending or waiting task |
| GET /api/openapi.json | Protected API contract |

Create body: `{"goal":"add 2 and 3","execute":true,"require_approval":false}`.
Action body: `{"revision": CURRENT_TASK_REVISION}`. Each action returns the new snapshot.
Stale revisions and invalid transitions return 409, missing tasks 404, and invalid fields
422. An unsupported but well-formed goal creates a saved failed task with a useful error.
Search treats percent signs and underscores literally. History limits range from 1 to 500;
offsets must be nonnegative. The dashboard loads 25 tasks at a time.

## Configuration and deployment

| Variable | Default |
| --- | --- |
| AGENTOS_API_TOKEN | Random startup token; configured values need at least 16 characters |
| AGENTOS_DATA_DIR | ~/.agentos |
| AGENTOS_DATABASE_URL | SQLite tasks.db in that directory |
| AGENTOS_ALLOWED_HOSTS | 127.0.0.1,localhost,[::1],testserver |

Export variables in the shell. Direct CLI use does not automatically load .env files.

Docker: copy .env.example to .env, choose a token, then run `docker compose up --build`.
Compose binds port 8000 to loopback and keeps the database in a named volume.
Remote hosting needs configured allowed hosts, TLS, and an appropriate access policy.

This first version uses one shared operator token, synchronous tools, and one server
worker. A process stopped while running a claimed task leaves its state running. It is
not automatically retried because a tool may already have produced a side effect.
Multi-user accounts, distributed workers, crash recovery, database migrations, and AI
provider integration remain follow-up work.

## Development

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check agent_engine tests
.\.venv\Scripts\python.exe -m build
```

The build produces a source distribution and a wheel in `dist/`, including the dashboard
and licensed fonts. Install a wheel with `python -m pip install PATH_TO_WHEEL`.

Tests cover parsing, unsupported/malicious expressions, schemas, approval enforcement,
typed references, retries, persistence, stale updates, concurrent execution claims,
API authentication, and CLI behavior. GitHub Actions checks Python 3.11, 3.12, and 3.14.

For optional browser checks, see scripts/verify-dashboard.cjs and
scripts/verify-dashboard-races.cjs. Playwright can live in a separate Node environment;
set PLAYWRIGHT_MODULE_PATH if it is not locally resolvable. Point AGENTOS_TEST_URL and
AGENTOS_TEST_TOKEN at an isolated server and database. The checks create real test tasks.
The second script covers delayed refreshes, selection errors, keyboard approvals,
mobile draft preservation, and disconnects during loading.

For example, install Playwright into an isolated directory and start a test server in
one PowerShell terminal:

```powershell
npm.cmd install --prefix .verification/browser --no-save --package-lock=false --ignore-scripts playwright
$env:AGENTOS_DATABASE_URL = "sqlite:///:memory:"
$env:AGENTOS_API_TOKEN = "dashboard-verification-token-2026"
.\.venv\Scripts\agentos.exe serve --port 8017
```

In a second terminal, from the same project directory:

```powershell
$env:PLAYWRIGHT_MODULE_PATH = (Resolve-Path .verification/browser/node_modules/playwright).Path
$env:AGENTOS_TEST_URL = "http://127.0.0.1:8017"
$env:AGENTOS_TEST_TOKEN = "dashboard-verification-token-2026"
node scripts/verify-dashboard.cjs
node scripts/verify-dashboard-races.cjs
```

These scripts use installed Microsoft Edge in headless mode. Stop the isolated server
with Ctrl+C when finished; its in-memory history is discarded. Browser screenshots are
written under `.verification/` and are excluded from Git.

```text
agent_engine/
  agent.py          # Orchestration and built-in registry
  state.py          # Task and step models
  tool_planner.py   # Executable arithmetic / JSON planner
  executor.py       # Retries, approval, typed references
  cli.py            # Task commands and dashboard server
  api.py            # Protected FastAPI service
  tools/            # Registry and calculators
  storage/          # SQLAlchemy repository
  web/              # Dashboard and licensed fonts
tests/              # Behavioral and integration tests
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for the development workflow and tool contracts,
[DESIGN.md](DESIGN.md) for the dashboard system, and [CHANGELOG.md](CHANGELOG.md) for changes.

The maintainer has not selected a project license. IBM Plex fonts include their SIL
Open Font License in agent_engine/web/fonts/OFL-IBM-Plex.txt.
