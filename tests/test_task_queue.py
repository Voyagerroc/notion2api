import pytest

import app.task_queue as tq


@pytest.fixture(autouse=True)
def temp_task_db(tmp_path, monkeypatch):
    db_file = tmp_path / "test_tasks.db"
    monkeypatch.setattr(tq, "DB_PATH", str(db_file))
    tq.init_task_db()
    yield db_file


def test_create_and_list_tasks():
    task_id = tq.create_task("Test Task", "Do something important")
    assert task_id is not None

    tasks = tq.list_tasks()
    assert len(tasks) == 1
    assert tasks[0]["id"] == task_id
    assert tasks[0]["title"] == "Test Task"
    assert tasks[0]["status"] == "pending"


def test_claim_and_complete_task():
    task_id = tq.create_task("Worker Job", "Run some job")

    claimed = tq._claim_next_task()
    assert claimed is not None
    assert claimed["id"] == task_id
    assert claimed["status"] == "running"
    assert claimed["lease_token"] is not None

    # Complete the task
    ok = tq._complete_task(task_id, claimed["lease_token"], "Execution result successfully finished")
    assert ok is True

    # Check status
    completed = next(t for t in tq.list_tasks() if t["id"] == task_id)
    assert completed["status"] == "completed"
    assert "Execution result" in completed["result"]


def test_claim_empty_queue():
    claimed = tq._claim_next_task()
    assert claimed is None


def test_task_retry_logic():
    task_id = tq.create_task("Failing Job", "Will fail once", max_retries=2)
    claimed = tq._claim_next_task()
    assert claimed is not None

    # Simulate a retryable failure (ConnectionError)
    exc = ConnectionError("Temporary connection failure")
    retryable = tq._mark_failure(claimed, exc)
    assert retryable is True

    task_entry = next(t for t in tq.list_tasks() if t["id"] == task_id)
    assert task_entry["status"] == "pending"
    assert task_entry["retry_count"] == 1
