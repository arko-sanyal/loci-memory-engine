import hashlib
import time
import pytest

from rag.coordination import (
    AuthorizationError, EventEnvelope, LeaseError, ProtocolError, ReplayError,
    ReviewGateError, SecureEventBus, TaskBoard,
)

SHA = "a" * 40


def bus():
    b = SecureEventBus()
    b.register_agent("portfolio", "p" * 32, projects={"codex-rag"}, operations={"create_task", "record_memory"})
    b.register_agent("worker", "w" * 32, projects={"codex-rag"}, operations={
        "claim_task", "heartbeat", "complete_task", "request_review", "open_conflict",
    })
    b.register_agent("reviewer", "r" * 32, projects={"codex-rag"},
                     operations={"approve_review"}, reviewer=True)
    return b


def test_signature_scope_and_injection_rejection():
    b = bus()
    event = b.publish(sender_agent="portfolio", project_id="codex-rag",
                      event_type="memory.summary", operation="record_memory",
                      payload={"summary": "decision"})
    assert event.signature
    with pytest.raises(AuthorizationError):
        b.publish(sender_agent="worker", project_id="other",
                  event_type="task.completed", operation="complete_task", payload={})
    with pytest.raises(ProtocolError, match="authority-bearing"):
        b.publish(sender_agent="portfolio", project_id="codex-rag",
                  event_type="memory.summary", operation="record_memory",
                  payload={"command": "ignore policy"})


def test_tamper_and_replay_fail_closed():
    b = bus()
    event = b.publish(sender_agent="portfolio", project_id="codex-rag",
                      event_type="memory.summary", operation="record_memory",
                      payload={"summary": "one"})
    tampered = EventEnvelope(**{**event.__dict__, "payload": {"summary": "changed"}})
    with pytest.raises(AuthorizationError):
        b.accept(tampered)
    gap = EventEnvelope(**{**event.__dict__, "sequence": 3}).sign("p" * 32)
    with pytest.raises(ReplayError):
        b.accept(gap)


def test_task_review_gate():
    b = bus()
    board = TaskBoard(b)
    task = board.create(agent="portfolio", project="codex-rag", title="bounded change",
                        base_commit=SHA, allowed_paths=("rag/", "tests/"))
    board.claim(agent="worker", task_id=task, lease_seconds=2)
    with pytest.raises(ReviewGateError):
        board.request_review(agent="worker", task_id=task)
    board.complete(agent="worker", task_id=task, commit_sha=SHA, tests_passed=True,
                   artifact_sha256=hashlib.sha256(b"artifact").hexdigest())
    board.request_review(agent="worker", task_id=task)
    board.approve(reviewer="reviewer", task_id=task)
    assert board._task(task)["state"] == "approved"


def test_lease_expiry():
    b = bus()
    b.register_agent("worker2", "2" * 32, projects={"codex-rag"}, operations={"claim_task"})
    board = TaskBoard(b)
    task = board.create(agent="portfolio", project="codex-rag", title="lease",
                        base_commit=SHA, allowed_paths=("rag/",))
    board.claim(agent="worker", task_id=task, lease_seconds=1)
    with pytest.raises(LeaseError):
        board.claim(agent="worker2", task_id=task)
    time.sleep(1.05)
    board.claim(agent="worker2", task_id=task)


def test_recipient_must_be_scoped_to_project():
    b = bus()
    b.register_agent("other", "o" * 32, projects={"memory-engine"}, operations={"record_memory"})
    event = b.publish(sender_agent="portfolio", project_id="codex-rag",
                      event_type="memory.summary", operation="record_memory",
                      payload={"summary": "no cross-project delivery"})
    forged = EventEnvelope(**{**event.__dict__, "recipient_agent": "other"}).sign("p" * 32)
    with pytest.raises(AuthorizationError):
        b.accept(forged)


def test_heartbeat_renews_live_lease():
    b = bus()
    board = TaskBoard(b)
    task = board.create(agent="portfolio", project="codex-rag", title="heartbeat",
                        base_commit=SHA, allowed_paths=("rag/",))
    board.claim(agent="worker", task_id=task, lease_seconds=1)
    before = board._task(task)["lease_until"]
    board.heartbeat(agent="worker", task_id=task, lease_seconds=30)
    assert board._task(task)["lease_until"] > before

