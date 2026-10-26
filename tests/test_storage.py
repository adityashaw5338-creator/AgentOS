from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

from agent_engine.agent import run_agent
from agent_engine.state import AgentState, AgentStatus
from agent_engine.storage.repository import ConcurrentUpdateError, TaskRepository


@pytest.fixture
def repository(tmp_path):
    repo = TaskRepository(f"sqlite:///{(tmp_path / 'tasks.db').as_posix()}")
    yield repo
    repo.close()


def test_snapshot_survives_reopening_database(repository):
    state = run_agent("calculate (2 + 3) * 4", repository=repository)
    reopened = TaskRepository(repository.database_url)
    try:
        stored = reopened.get_task(state.task_id)
        assert stored.model_dump() == state.model_dump()
        assert stored.steps[0].result == 5
        assert stored.steps[1].tool_args["a"] == {"$ref": 1}
        assert stored.status == AgentStatus.COMPLETED
        assert stored.created_at.utcoffset().total_seconds() == 0
    finally:
        reopened.close()


def test_stale_update_cannot_overwrite_saved_task(repository):
    state = run_agent("add 2 and 3", repository=repository, execute=False)
    stale = repository.get_task(state.task_id)
    state.status = AgentStatus.CANCELLED
    repository.save_task(state)
    stale.status = AgentStatus.COMPLETED
    with pytest.raises(ConcurrentUpdateError):
        repository.save_task(stale)
    assert stale.revision == 1
    assert repository.get_task(state.task_id).status == AgentStatus.CANCELLED


def test_two_database_clients_cannot_claim_same_revision(repository):
    state = run_agent("add 2 and 3", repository=repository, execute=False)
    second = TaskRepository(repository.database_url)
    try:
        contenders = [repository.get_task(state.task_id), second.get_task(state.task_id)]

        def claim(pair):
            repo, candidate = pair
            candidate.status = AgentStatus.RUNNING
            try:
                repo.save_task(candidate)
                return True
            except ConcurrentUpdateError:
                return False

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(claim, zip([repository, second], contenders)))
        assert sorted(results) == [False, True]
        assert repository.get_task(state.task_id).revision == 2
    finally:
        second.close()


def test_duplicate_new_task_is_rejected(repository):
    state = AgentState(goal="add 2 and 3")
    repository.save_task(state)
    with pytest.raises(ConcurrentUpdateError):
        repository.save_task(AgentState(task_id=state.task_id, goal="different"))


def test_pagination_filters_and_literal_search(repository):
    first = AgentState(goal="100% of a_value")
    second = AgentState(goal="1000 of anyvalue", status=AgentStatus.FAILED)
    third = AgentState(goal="100% of other_value")
    for index, state in enumerate((first, second, third)):
        state.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=index)
        repository.save_task(state)
    assert repository.count_tasks(search="100%") == 2
    assert repository.count_tasks(search="a_value") == 1
    assert repository.count_tasks(status="failed") == 1
    assert repository.list_tasks(limit=1)[0].task_id == third.task_id
    assert repository.list_tasks(limit=1, offset=1)[0].task_id == second.task_id
    assert repository.stats()["total"] == 3
    assert repository.get_task("missing") is None


@pytest.mark.parametrize("limit,offset", [(0, 0), (501, 0), (10, -1)])
def test_invalid_pagination(repository, limit, offset):
    with pytest.raises(ValueError):
        repository.list_tasks(limit=limit, offset=offset)
