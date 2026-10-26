# Changelog

## 0.1.0 — Unreleased

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
