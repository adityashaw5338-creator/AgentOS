# AgentOS

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Local workflow operators and Python developers who build and inspect registered tool
workflows, review execution results, and approve sensitive tool calls.

## Product Purpose

Turn supported goals into validated execution steps, run them, preserve their history,
and pause for human approval when a step needs it.

## Operating Context

A Python command starts the local web dashboard and protected API. Operators enter
arithmetic goals or structured plans, inspect results and logs, and approve or cancel
waiting tasks. The CLI and dashboard use the same persistent database.

## Capabilities and Constraints

The existing repository establishes Python, Pydantic, SQLAlchemy, planning, tools, retries,
and human approval as the foundation. Built-in tools perform arithmetic. Arbitrary research,
shell access, file editing, and a configured AI provider are outside this first version.
The dashboard displays real saved tasks; a new database starts empty.

## Brand Commitments

Keep the name AgentOS and the existing modular engine concept.

## Evidence on Hand

The modular Python package, bundled dashboard, CLI, API, and behavioral tests establish
the implemented capabilities. Python tests cover planning, validation, approvals, retries,
persistence, concurrency, authentication, and custom tools. Browser checks exercise real
task flows and delayed responses at desktop, tablet, and phone widths. Report validation
from actual test runs; no customer claims or sample history are supplied with the app.

## Open Decisions

Public hosting, multi-user accounts, a broader tool catalog, licensing, and an AI provider
remain future decisions. The initial frontend implementation is a bundled static interface
served by the Python backend, chosen to keep installation simple.
