# Changelog

## 0.2.0 — 2026-10-27

### Added

- Optional OpenAI Responses planning with structured output, local tool/argument validation,
  mandatory per-step approvals, bounded requests, and sanitized provider errors.
- Dashboard planner selection, authenticated configuration metadata, per-task API selection,
  and CLI `--planner` overrides. Local planning remains the default without credentials.
- Durable planning records and execution checkpoints before attempts and after successful steps.
- Explicit interrupted-run recovery through CLI and API, preserving history without replaying tools.
- Portable browser runner with isolated database/provider configuration and Chromium verification in CI.
- Regression coverage for AI/API/CLI approval flows, provider failures, interrupted tasks,
  independent task execution, CORS, planner selection, and delayed dashboard metadata.

### Fixed

- A slow synchronous tool no longer holds a service-wide lock over unrelated task requests.
- Invalid CORS hosts, ports, credentials, and paths are rejected; equivalent origins are normalized.
- Storage checkpoint failures stop execution without entering the tool retry loop.
- Removed unused alternative storage modules with an incompatible schema; existing task snapshots
  continue to use `agent_engine.storage.repository` without a database migration.

### Scope

The local app supports one operator and registered synchronous tools. Recovery requires the
operator to stop the worker and inspect possible side effects. AI provider access is configured
by the operator; automated tests use HTTP mocks. Multi-user hosting and distributed workers
remain outside this release.

## 0.1.0 — 2026-10-26

### Added

- Installable `agentos-engine` Python package and `agentos` command, preserving legacy entry points.
- Deterministic arithmetic and explicit JSON plans with validated tool arguments and prior-result references.
- Tool registry schemas, mandatory approvals, bounded retries, and saved task results and logs.
- SQLAlchemy task history with optimistic revisions and execution claims across clients.
- Protected FastAPI endpoints and a bundled dashboard for task creation, previews, approvals,
  cancellation, history search, pagination, and tool inspection.
- Responsive layouts, keyboard controls, self-hosted IBM Plex fonts, and token storage in tab memory.
- Engine and API regression tests, real-browser verification scripts, Python CI, and Docker configuration.

### Fixed

- Typed custom tools receive nested Pydantic model instances through direct execution and saved approvals.
- Older dashboard refreshes and selection errors cannot overwrite the current task state.
- Approval actions preserve keyboard focus; history refreshes preserve mobile drafts.
- Disconnect clears workspace data, messages, and loading state.
- CLI history supports offsets and consistent limits; unexpected saved execution failures remain in history.

### Scope

The initial version uses deterministic planning, synchronous tools, one operator token,
and one server worker. AI providers, multi-user accounts, distributed workers, and crash
recovery remain future work.
