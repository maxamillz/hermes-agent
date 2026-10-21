"""A worker's late timeout must not mutate a handoff or successor run."""
from pathlib import Path

import pytest

from hermes_cli import kanban_db as db


@pytest.mark.parametrize("reclaim", [False, True])
def test_late_timeout_preserves_handoff(tmp_path, monkeypatch, reclaim):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    db.init_db()
    with db.connect() as conn:
        tid = db.create_task(conn, title="candidate needs owner review", assignee="worker")
        old = db.claim_task(conn, tid)
        assert old is not None
        assert db.block_task(conn, tid, reason="Owner review", kind="needs_input",
                             expected_run_id=old.current_run_id)
        if reclaim:
            assert db.unblock_task(conn, tid)
            successor = db.claim_task(conn, tid)
            assert successor is not None
            assert successor.current_run_id != old.current_run_id
        before = list(conn.iterdump())
        assert not db._record_task_failure(
            conn, tid, "late budget callback", outcome="timed_out",
            expected_run_id=old.current_run_id, release_claim=True, end_run=True,
        )
        assert list(conn.iterdump()) == before


def test_current_run_timeout_still_trips_breaker(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    db.init_db()
    with db.connect() as conn:
        tid = db.create_task(conn, title="real timeout", assignee="worker")
        current = db.claim_task(conn, tid)
        assert current is not None
        assert db._record_task_failure(
            conn, tid, "real budget exhaustion", outcome="timed_out",
            expected_run_id=current.current_run_id, release_claim=True,
            end_run=True, failure_limit=1,
        )
        assert db.get_task(conn, tid).status == "blocked"
        run = conn.execute("SELECT outcome FROM task_runs WHERE id=?",
                           (current.current_run_id,)).fetchone()
        assert run["outcome"] == "gave_up"
