"""Validated task state shared by the CLI, executor, and persistence layer."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AgentStatus(str, Enum):
    PLANNING = "planning"
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    CANCELLED = "cancelled"


class PlanStep(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    step_id: int = Field(ge=1, strict=True)
    description: str = Field(min_length=1, max_length=4000)
    tool_name: str | None = None
    tool_args: dict[str, Any] = Field(default_factory=dict)
    requires_approval: bool = Field(default=False, strict=True)
    approved: bool = Field(default=False, strict=True)
    completed: bool = Field(default=False, strict=True)
    result: Any = None
    attempts: int = Field(default=0, ge=0, strict=True)


class AgentState(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    task_id: str = Field(default_factory=lambda: str(uuid4()), min_length=1, max_length=128)
    goal: str = Field(max_length=4000)
    steps: list[PlanStep] = Field(default_factory=list, max_length=128)
    current_step: int = Field(default=0, ge=0, strict=True)
    status: AgentStatus = AgentStatus.PENDING
    result: str | None = None
    error: str | None = None
    execution_log: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    revision: int = Field(default=0, ge=0, strict=True)

    @field_validator("created_at", "updated_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Task timestamps must include a timezone.")
        return value.astimezone(timezone.utc)
