"""A protected local API and the bundled AgentOS dashboard."""

from __future__ import annotations

import os
import secrets
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, StringConstraints
from starlette.middleware.trustedhost import TrustedHostMiddleware

from agent_engine import __version__
from agent_engine.agent import build_registry, recover_task, run_agent
from agent_engine.executor import approve_current_step, execute_plan
from agent_engine.planner import planner_info
from agent_engine.state import AgentState, AgentStatus
from agent_engine.storage.repository import (
    ConcurrentUpdateError,
    TaskRepository,
    default_database_url,
)
from agent_engine.tools.registry import ToolRegistry

DEFAULT_CORS_ORIGINS = (
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
)


@dataclass
class Settings:
    api_token: str = field(default_factory=lambda: secrets.token_urlsafe(32))
    database_url: str = field(default_factory=default_database_url)
    allowed_hosts: tuple[str, ...] = ("127.0.0.1", "localhost", "[::1]", "testserver")
    cors_origins: tuple[str, ...] = DEFAULT_CORS_ORIGINS

    def __post_init__(self):
        if len(self.api_token) < 16:
            raise ValueError("AGENTOS_API_TOKEN must have at least 16 characters.")
        origins = []
        for value in self.cors_origins:
            origin = value.strip()
            try:
                parsed = urlsplit(origin)
                # urlsplit leaves port validation lazy and silently removes some control
                # characters; reject those inputs before normalizing a browser origin.
                port = parsed.port
                if (
                    parsed.scheme not in {"http", "https"}
                    or not parsed.hostname
                    or parsed.path not in {"", "/"}
                    or "?" in origin
                    or "#" in origin
                    or parsed.username is not None
                    or parsed.password is not None
                    or parsed.netloc.endswith(":")
                    or "*" in parsed.netloc
                    or "\\" in origin
                    or any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in origin)
                    or (port is not None and not 0 <= port <= 65535)
                ):
                    raise ValueError("Invalid origin.")
                # CORS compares serialized origins exactly, including lower-case hosts,
                # IDNA names, and omitted default ports.
                origins.append(str(AnyHttpUrl(origin)).removesuffix("/"))
            except ValueError as error:
                raise ValueError(
                    "CORS origins must be exact http or https origins with a valid host "
                    "and port, without credentials, paths, queries, or fragments."
                ) from error
        self.cors_origins = tuple(dict.fromkeys(origins))

    @classmethod
    def from_env(cls) -> Settings:
        values = {}
        if token := os.environ.get("AGENTOS_API_TOKEN"):
            values["api_token"] = token
        if hosts := os.environ.get("AGENTOS_ALLOWED_HOSTS"):
            values["allowed_hosts"] = tuple(
                host.strip() for host in hosts.split(",") if host.strip()
            )
        if "AGENTOS_CORS_ORIGINS" in os.environ:
            values["cors_origins"] = tuple(
                origin.strip()
                for origin in os.environ["AGENTOS_CORS_ORIGINS"].split(",")
                if origin.strip()
            )
        return cls(**values)


class NewTask(BaseModel):
    model_config = ConfigDict(extra="forbid")
    goal: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
    execute: bool = Field(default=True, strict=True)
    require_approval: bool = Field(default=False, strict=True)
    planner: Literal["local", "openai"] | None = None


class TaskAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=1, strict=True)


class RecoveryAction(TaskAction):
    confirm_stopped: bool = Field(default=False, strict=True)


class TaskService:
    def __init__(self, repository: TaskRepository, registry: ToolRegistry):
        self.repository = repository
        self.registry = registry

    def task(self, task_id: str) -> AgentState:
        state = self.repository.get_task(task_id)
        if state is None:
            raise HTTPException(404, "Task not found.")
        return state

    def create(self, request: NewTask) -> AgentState:
        return run_agent(
            request.goal,
            registry=self.registry,
            repository=self.repository,
            execute=request.execute,
            require_approval=request.require_approval,
            planner=request.planner,
        )

    def action(self, task_id: str, action: str, revision: int) -> AgentState:
        state = self.task(task_id)
        if state.revision != revision:
            raise HTTPException(409, "Task changed. Refresh it before continuing.")
        if action == "cancel":
            if state.status not in {
                AgentStatus.PENDING,
                AgentStatus.PLANNING,
                AgentStatus.WAITING_FOR_APPROVAL,
            }:
                raise HTTPException(409, "Only a pending task or a waiting task can be cancelled.")
            state.status = AgentStatus.CANCELLED
            state.error = None
            state.execution_log.append("Task cancelled by the user.")
            return self.repository.save_task(state)
        if action == "approve":
            if state.status != AgentStatus.WAITING_FOR_APPROVAL:
                raise HTTPException(409, "Task is not waiting for approval.")
            approve_current_step(state)
        elif state.status != AgentStatus.PENDING:
            raise HTTPException(409, "Only a pending task can be executed.")
        # Compare-and-swap protects each task without holding up unrelated tasks.
        state.status = AgentStatus.RUNNING
        self.repository.save_task(state)
        try:
            execute_plan(state, self.registry, checkpoint=self.repository.save_task)
        except ConcurrentUpdateError:
            raise
        except Exception:
            state.status = AgentStatus.FAILED
            state.error = "Execution failed unexpectedly; inspect the saved task before retrying."
            state.execution_log.append(state.error)
        return self.repository.save_task(state)

    def recover(self, task_id: str, request: RecoveryAction) -> AgentState:
        state = self.task(task_id)
        if state.revision != request.revision:
            raise HTTPException(409, "Task changed. Refresh it before continuing.")
        try:
            recover_task(state, confirm_stopped=request.confirm_stopped)
        except ValueError as error:
            raise HTTPException(409, str(error)) from error
        return self.repository.save_task(state)


def create_app(
    settings: Settings | None = None,
    repository: TaskRepository | None = None,
    registry: ToolRegistry | None = None,
) -> FastAPI:
    settings = settings or Settings.from_env()
    owns_repository = repository is None
    repository = repository or TaskRepository(settings.database_url)
    registry = registry or build_registry()
    service = TaskService(repository, registry)

    @asynccontextmanager
    async def lifespan(app):
        yield
        if owns_repository:
            repository.close()

    app = FastAPI(
        title="AgentOS",
        version=__version__,
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.service = service
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
    )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(settings.allowed_hosts))
    bearer = HTTPBearer(auto_error=False)

    def require_token(
        credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    ):
        if credentials is None or not secrets.compare_digest(
            credentials.credentials.encode("utf-8"),
            settings.api_token.encode("utf-8"),
        ):
            raise HTTPException(
                401,
                "Enter the access token shown by agentos serve.",
                headers={"WWW-Authenticate": "Bearer"},
            )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; font-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; object-src 'none'; "
            "base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
        )
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(ConcurrentUpdateError)
    async def changed_task(request, error):
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=409, content={"detail": str(error)})

    @app.get("/api/health")
    def health():
        return {"status": "ok", "version": __version__}

    router = APIRouter(prefix="/api", dependencies=[Depends(require_token)])

    @router.get("/planner")
    def planning_configuration():
        return planner_info()

    @router.get("/tools")
    def tools():
        return {"tools": registry.list_tools()}

    @router.get("/stats")
    def stats():
        return repository.stats()

    @router.get("/tasks")
    def tasks(
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
        offset: Annotated[int, Query(ge=0)] = 0,
        status: AgentStatus | None = None,
        search: Annotated[str | None, Query(max_length=4000)] = None,
    ):
        return {
            "tasks": repository.list_tasks(limit, offset, status, search),
            "total": repository.count_tasks(status, search),
            "limit": limit,
            "offset": offset,
        }

    @router.post("/tasks", status_code=201, response_model=AgentState)
    def create_task(request: NewTask):
        return service.create(request)

    @router.get("/tasks/{task_id}", response_model=AgentState)
    def get_task(task_id: str):
        return service.task(task_id)

    @router.post("/tasks/{task_id}/execute", response_model=AgentState)
    def execute_task(task_id: str, request: TaskAction):
        return service.action(task_id, "execute", request.revision)

    @router.post("/tasks/{task_id}/approve", response_model=AgentState)
    def approve_task(task_id: str, request: TaskAction):
        return service.action(task_id, "approve", request.revision)

    @router.post("/tasks/{task_id}/cancel", response_model=AgentState)
    def cancel_task(task_id: str, request: TaskAction):
        return service.action(task_id, "cancel", request.revision)

    @router.post("/tasks/{task_id}/recover", response_model=AgentState)
    def recover_interrupted_task(task_id: str, request: RecoveryAction):
        return service.recover(task_id, request)

    @router.get("/openapi.json", include_in_schema=False)
    def openapi():
        return app.openapi()

    app.include_router(router)
    web_dir = Path(__file__).parent / "web"
    if web_dir.is_dir():
        app.mount("/static", StaticFiles(directory=web_dir), name="static")

    @app.get("/", include_in_schema=False)
    def dashboard():
        return FileResponse(web_dir / "index.html")

    return app
