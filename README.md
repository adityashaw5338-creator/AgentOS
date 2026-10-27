# AgentOS

A modular Python agent engine with validated tools, persistent task history, a protected
API, and a local dashboard.

The local planner supports arithmetic requests and explicit JSON tool plans, with
no API key required. Optional AI planning translates natural-language goals into
validated calls to the same registered tools. The dashboard and CLI share persisted task history.

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

Version 0.2.0 adds optional AI planning, execution checkpoints, interrupted-run recovery,
and browser verification in CI. Existing task databases remain compatible.

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
.\.venv\Scripts\agentos.exe run --planner local "add 2 and 3"
```

Legacy entry points work: `python -m agent_engine.cli "add 2 and 3"` and
`python cli.py history`. Use --help for options. Failed tasks return a nonzero CLI exit
code and remain in history.

In the dashboard, enter a goal and choose Run task or Preview plan. Enable Require approval
to pause before every tool call. Approving releases only the current step. Pending and
waiting tasks can be cancelled. The CLI and dashboard share history with the same database.

## Optional AI planning

AI planning uses the OpenAI Responses API, or an endpoint implementing the same API and
structured-output contract. Choose a model available to your account that supports Responses
structured outputs. There is no default model and no provider request until AI mode is selected.
Provider usage may incur charges.

Configure the server's environment before starting it:

```powershell
$env:OPENAI_API_KEY = "YOUR_API_KEY"
$env:AGENTOS_MODEL = "YOUR_RESPONSES_MODEL"
.\.venv\Scripts\agentos.exe serve
```

The dashboard's **Planner** selector enables **AI** when configuration is present. Keys stay
on the server. Configuration availability does not verify account access; provider errors appear
on the saved task. Local mode remains usable without a provider. An AI request sends the task
goal and registered tool definitions to the configured provider, with response storage disabled.

CLI example:

```powershell
.\.venv\Scripts\agentos.exe plan --planner openai "Add a 15 percent tip to a bill of 80 and split it between 4 people"
.\.venv\Scripts\agentos.exe resume TASK_ID
.\.venv\Scripts\agentos.exe approve TASK_ID
```

Set `AGENTOS_PLANNER=openai` to make AI the server/CLI default, or select it for an individual
task. `--planner local` always avoids provider calls. Direct API requests can supply
`"planner":"local"` or `"planner":"openai"`; omitting it uses the configured default.

AI only proposes plans. Every tool name, argument, reference, and step limit is checked locally;
every AI-generated step requires approval. Approving or resuming a saved plan does not call the
provider again. Unknown tools, malformed plans, refusals, and incomplete responses become saved
failures without executing tools. Provider credentials and error bodies are not written to history.

The built-in tools still perform arithmetic. AI planning does not add web browsing, shell access,
or file editing. Register typed custom tools in Python to extend the available capabilities.
The integration follows the official [Responses API](https://developers.openai.com/api/reference/resources/responses/methods/create)
and [structured output](https://developers.openai.com/api/docs/guides/structured-outputs) contracts.

## Engine behavior

- Local planning compiles anchored arithmetic requests or a bounded AST into actual tool calls.
- Optional AI planning proposes validated tool calls with mandatory human approval.
- Pydantic validates typed tool arguments, rejects unexpected fields, and generates schemas.
- Execution resolves prior results, records outputs and attempts, and enforces approval gates.
- ValueError is permanent; other tool exceptions may be retried, with bounded attempts.
- SQLAlchemy stores complete task snapshots and uses optimistic revisions for updates.
- Goals are saved before planning; execution attempts and successful results are checkpointed.
- Resuming clients claim a task before execution to avoid simultaneous duplicate tool calls.
- Independent tasks can progress while another task waits on a synchronous tool or provider.
- Bearer tokens protect task data and actions. The dashboard keeps its token in memory.

Built-in tools are add, subtract, multiply, divide, and power. Goals are limited to
4,000 characters and plans to 32 steps. Calculator values must be finite real numbers
with magnitude at most 1e100; exponents are bounded.

Arbitrary Python, shell commands, file access, and web research are not built-in tools.
The default planner is deterministic; optional AI planning uses only the installed tool catalog.

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
Different tasks may call the same tool concurrently. Protect shared mutable state with
the tool's own lock or use a thread-safe client.
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
| GET /api/planner | Default planner and safe provider configuration availability |
| GET /api/stats | Counts by task state |
| GET /api/tasks | History; limit, offset, status, search |
| GET /api/tasks/{id} | Task snapshot |
| POST /api/tasks | Create a task |
| POST /api/tasks/{id}/execute | Execute a pending preview |
| POST /api/tasks/{id}/approve | Approve the current waiting step and continue |
| POST /api/tasks/{id}/cancel | Cancel a pending or waiting task |
| POST /api/tasks/{id}/recover | Close an interrupted task after confirming its worker has stopped |
| GET /api/openapi.json | Protected API contract |

Create body: `{"goal":"add 2 and 3","execute":true,"require_approval":false}`.
Action body: `{"revision": CURRENT_TASK_REVISION}`. Each action returns the new snapshot.
Recovery additionally requires `"confirm_stopped":true`. Recovery records a failure without
replaying tools; it is not a retry command.
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
| AGENTOS_CORS_ORIGINS | localhost and 127.0.0.1 on ports 3000 and 5173 |
| AGENTOS_PLANNER | local; use openai to opt into AI by default |
| OPENAI_API_KEY | Unset; required for AI planning |
| AGENTOS_MODEL | Unset; a Responses structured-output model is required for AI |
| OPENAI_BASE_URL | https://api.openai.com/v1; HTTPS, or HTTP on loopback for a local provider |
| AGENTOS_AI_TIMEOUT | 20 seconds; configurable from 1 to 120 |

For a separately hosted frontend, set `AGENTOS_CORS_ORIGINS` to its exact origin or
comma-separated origins before starting the server. For example, in PowerShell:

```powershell
$env:AGENTOS_CORS_ORIGINS = "http://localhost:5173"
.\.venv\Scripts\agentos.exe serve
```

Origins must include the scheme and host (and port when used). Wildcards, credentials,
paths, and malformed ports are rejected. Equivalent browser origins are normalized;
browser requests still need the API bearer token. Set an empty AGENTOS_CORS_ORIGINS to disable CORS.

Export variables in the shell. Direct CLI use does not automatically load .env files.

Docker: copy .env.example to .env, choose a token, then run `docker compose up --build`.
Compose binds port 8000 to loopback and keeps the database in a named volume.
Remote hosting needs configured allowed hosts, TLS, and an appropriate access policy.

The local app uses one shared operator token, synchronous tools, and one server worker.
Long-running tools cannot be forcibly cancelled. Multi-user accounts, distributed workers,
and public hosting remain outside this local-app release.

## Interrupted runs

A stopped process leaves its task in `planning` or `running`, with all previously saved
steps and the last started attempt available for inspection. Stop the process that owned
the task before recovering it. Recovery does not detect or terminate a live worker.

```powershell
.\.venv\Scripts\agentos.exe show TASK_ID
.\.venv\Scripts\agentos.exe recover TASK_ID --confirm-stopped
```

Recovery marks the interrupted task failed and preserves its history. Tools are never
automatically replayed after a crash. A tool may have completed an external action before
its result was saved, so review that action before creating another task. Custom tools
should use idempotency keys where appropriate. Existing 0.1.0 snapshots remain readable;
the unused alternative storage modules were removed in favor of `storage.repository`.

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
API authentication, CORS, interrupted runs, independent task execution, and CLI behavior.
AI request/response and approval flows use controlled HTTP transports; tests never inherit
provider credentials or make paid API calls. GitHub Actions checks Python 3.11, 3.12, and 3.14
and runs the browser suites in Chromium.

Run the browser suites with the portable runner. It starts an isolated server on an available
loopback port, generates a test token, uses an in-memory database, disables real AI calls,
and shuts down the server after success or failure. No separate server terminal is needed.
Node.js 22 or newer is required.

```powershell
npm.cmd install --prefix .verification/browser --no-save --package-lock=false --ignore-scripts playwright@1.64.1
node .verification/browser/node_modules/playwright/cli.js install chromium
$env:PLAYWRIGHT_MODULE_PATH = (Resolve-Path .verification/browser/node_modules/playwright).Path
node scripts/verify-browser.cjs
```

To use installed Microsoft Edge instead of downloading Chromium, set
`AGENTOS_BROWSER_CHANNEL=msedge`. Set `AGENTOS_TEST_PYTHON` when Python is outside the project's
`.venv` or PATH. On macOS/Linux, use `npm` and export the same variables in your shell.

The suites cover task flows, planner selection, responsive layouts, delayed refreshes,
selection errors, keyboard approvals, mobile draft preservation, and disconnects during loading.
Screenshots and logs are written under `.verification/` and excluded from Git. The individual
`verify-dashboard.cjs` and `verify-dashboard-races.cjs` scripts can still target a manually isolated
server using `AGENTOS_TEST_URL` and `AGENTOS_TEST_TOKEN`.

```text
agent_engine/
  agent.py          # Orchestration and built-in registry
  state.py          # Task and step models
  tool_planner.py   # Executable arithmetic / JSON planner
  ai_planner.py     # Optional Responses planner and local output validation
  planner.py        # Planner selection and safe configuration metadata
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
