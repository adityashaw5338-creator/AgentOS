"""Durable task snapshots with optimistic concurrency protection."""

from __future__ import annotations

import os
from pathlib import Path
from threading import RLock

from sqlalchemy import Integer, String, Text, create_engine, func, select, update
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column
from sqlalchemy.pool import StaticPool

from agent_engine.state import AgentState, AgentStatus, utc_now


class ConcurrentUpdateError(ValueError):
    """The task has changed since the caller loaded it."""


class Base(DeclarativeBase):
    pass


class TaskRecord(Base):
    __tablename__ = "tasks"

    task_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    goal: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), index=True)
    created_at: Mapped[str] = mapped_column(String(64), index=True)
    updated_at: Mapped[str] = mapped_column(String(64))
    revision: Mapped[int] = mapped_column(Integer)
    snapshot: Mapped[str] = mapped_column(Text)


def default_database_url() -> str:
    """Use a persistent per-user directory, independent of the current checkout."""
    configured = os.environ.get("AGENTOS_DATABASE_URL")
    if configured:
        return configured
    data_dir = Path(os.environ.get("AGENTOS_DATA_DIR", str(Path.home() / ".agentos")))
    return f"sqlite:///{(data_dir / 'tasks.db').resolve().as_posix()}"


class TaskRepository:
    def __init__(self, database_url: str | None = None):
        self.database_url = database_url or default_database_url()
        url = make_url(self.database_url)
        options: dict = {}
        if url.get_backend_name() == "sqlite":
            options["connect_args"] = {"check_same_thread": False, "timeout": 10}
            if url.database in (None, "", ":memory:"):
                options["poolclass"] = StaticPool
            else:
                Path(url.database).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(self.database_url, **options)
        self._lock = RLock()
        Base.metadata.create_all(self.engine)

    def save_task(self, state: AgentState) -> AgentState:
        """Insert or compare-and-swap a snapshot; mutate revision only after commit."""
        expected_revision = state.revision
        saved = state.model_copy(deep=True)
        saved.revision = expected_revision + 1
        saved.updated_at = utc_now()
        values = {
            "goal": saved.goal,
            "status": saved.status.value,
            "updated_at": saved.updated_at.isoformat(),
            "revision": saved.revision,
            "snapshot": saved.model_dump_json(),
        }
        with self._lock, Session(self.engine) as session, session.begin():
            if expected_revision == 0:
                if session.get(TaskRecord, state.task_id) is not None:
                    raise ConcurrentUpdateError("Task already exists. Reload it before continuing.")
                session.add(
                    TaskRecord(
                        task_id=saved.task_id,
                        created_at=saved.created_at.isoformat(),
                        **values,
                    )
                )
            else:
                changed = session.execute(
                    update(TaskRecord)
                    .where(TaskRecord.task_id == state.task_id)
                    .where(TaskRecord.revision == expected_revision)
                    .values(**values)
                ).rowcount
                if changed != 1:
                    raise ConcurrentUpdateError("Task changed. Reload it before continuing.")
        state.revision = saved.revision
        state.updated_at = saved.updated_at
        return state

    @staticmethod
    def _filters(statement, status: AgentStatus | str | None, search: str | None):
        if status:
            statement = statement.where(TaskRecord.status == AgentStatus(status).value)
        if search:
            # Bind parameters and escape SQL wildcard characters: search is literal text.
            escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            statement = statement.where(TaskRecord.goal.ilike(f"%{escaped}%", escape="\\"))
        return statement

    def get_task(self, task_id: str) -> AgentState | None:
        with self._lock, Session(self.engine) as session:
            record = session.get(TaskRecord, task_id)
            return AgentState.model_validate_json(record.snapshot) if record else None

    def list_tasks(
        self,
        limit: int = 100,
        offset: int = 0,
        status: AgentStatus | str | None = None,
        search: str | None = None,
    ) -> list[AgentState]:
        if not 1 <= limit <= 500 or offset < 0:
            raise ValueError("Use a limit from 1 to 500 and a nonnegative offset.")
        query = (
            self._filters(select(TaskRecord), status, search)
            .order_by(
                TaskRecord.created_at.desc(),
                TaskRecord.task_id.desc(),
            )
            .limit(limit)
            .offset(offset)
        )
        with self._lock, Session(self.engine) as session:
            return [AgentState.model_validate_json(row.snapshot) for row in session.scalars(query)]

    def count_tasks(
        self, status: AgentStatus | str | None = None, search: str | None = None
    ) -> int:
        query = self._filters(select(func.count()).select_from(TaskRecord), status, search)
        with self._lock, Session(self.engine) as session:
            return session.scalar(query) or 0

    def stats(self) -> dict[str, int]:
        counts = {status.value: 0 for status in AgentStatus}
        with self._lock, Session(self.engine) as session:
            for status, count in session.execute(
                select(TaskRecord.status, func.count()).group_by(TaskRecord.status)
            ):
                counts[status] = count
        return {"total": sum(counts.values()), **counts}

    def close(self) -> None:
        self.engine.dispose()


_repositories: dict[str, TaskRepository] = {}
_repository_lock = RLock()


def get_repository() -> TaskRepository:
    url = default_database_url()
    with _repository_lock:
        if url not in _repositories:
            _repositories[url] = TaskRepository(url)
        return _repositories[url]


def save_task(state: AgentState) -> AgentState:
    return get_repository().save_task(state)


def get_task(task_id: str) -> dict | None:
    state = get_repository().get_task(task_id)
    return state.model_dump(mode="json") if state else None


def list_tasks(limit: int = 100, offset: int = 0) -> list[dict]:
    return [state.model_dump(mode="json") for state in get_repository().list_tasks(limit, offset)]
