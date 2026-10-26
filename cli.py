"""Compatibility entry point; the implementation lives in agent_engine."""

from agent_engine.cli import entrypoint as entrypoint
from agent_engine.cli import main as main

if __name__ == "__main__":
    entrypoint()
