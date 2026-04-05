from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from run_store import ClaimRequest, RunStore, StatusTransitionError, TaskRun


def make_run(*, run_id: str = "run-1", task_key: str = "AB#123", status: str = "claimed") -> TaskRun:
    return TaskRun(
        run_id=run_id,
        provider_type="azure-devops",
        task_id="123",
        task_key=task_key,
        session_id=f"session-{run_id}",
        executor_type="codex-acp",
        status=status,
    )


class RunStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "harness.db"
        self.store = RunStore(self.db_path)
        self.store.initialize()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_record_event_deduplicates_by_fingerprint(self) -> None:
        created = self.store.record_event(
            "event-1",
            source_type="task.created",
            source_id="evt-1",
            received_at="2026-04-05T12:00:00Z",
            expires_at="2026-04-06T12:00:00Z",
        )
        duplicate = self.store.record_event(
            "event-1",
            source_type="task.created",
            source_id="evt-1",
            received_at="2026-04-05T12:00:01Z",
            expires_at="2026-04-06T12:00:01Z",
        )

        self.assertTrue(created)
        self.assertFalse(duplicate)

    def test_acquire_lock_rejects_second_owner_until_expiry(self) -> None:
        created_run = self.store.create_run(make_run())
        acquired = self.store.acquire_lock(
            created_run.task_key,
            run_id=created_run.run_id,
            owner="worker-a",
            acquired_at="2026-04-05T12:00:00Z",
            ttl_seconds=60,
        )
        rejected = self.store.acquire_lock(
            created_run.task_key,
            run_id=created_run.run_id,
            owner="worker-b",
            acquired_at="2026-04-05T12:00:30Z",
            ttl_seconds=60,
        )
        recovered = self.store.acquire_lock(
            created_run.task_key,
            run_id=created_run.run_id,
            owner="worker-b",
            acquired_at="2026-04-05T12:01:01Z",
            ttl_seconds=60,
        )

        self.assertTrue(acquired.acquired)
        self.assertFalse(rejected.acquired)
        self.assertEqual("worker-a", rejected.owner)
        self.assertTrue(recovered.acquired)

    def test_claim_run_accepts_first_request(self) -> None:
        outcome = self.store.claim_run(
            ClaimRequest(
                fingerprint="fingerprint-1",
                source_type="task.created",
                source_id="evt-1",
                owner="worker-a",
                run=make_run(),
            ),
            now="2026-04-05T12:00:00Z",
        )

        self.assertTrue(outcome.accepted)
        self.assertEqual("claimed", outcome.run.status)
        self.assertEqual(outcome.run, self.store.get_run("run-1"))

        audit = self.store.list_audit("run-1")
        self.assertEqual(["run_claimed"], [entry["event_type"] for entry in audit])

    def test_claim_run_rejects_duplicate_event_fingerprint(self) -> None:
        first = self.store.claim_run(
            ClaimRequest(
                fingerprint="fingerprint-1",
                source_type="task.created",
                source_id="evt-1",
                owner="worker-a",
                run=make_run(run_id="run-1"),
            ),
            now="2026-04-05T12:00:00Z",
        )
        self.store.transition_status(
            "run-1",
            to_status="failed",
            expected_from="claimed",
            updated_at="2026-04-05T12:01:00Z",
        )

        duplicate = self.store.claim_run(
            ClaimRequest(
                fingerprint="fingerprint-1",
                source_type="task.created",
                source_id="evt-1",
                owner="worker-b",
                run=make_run(run_id="run-2"),
            ),
            now="2026-04-05T12:02:00Z",
        )

        self.assertTrue(first.accepted)
        self.assertFalse(duplicate.accepted)
        self.assertEqual("duplicate_event", duplicate.reason)
        self.assertIsNone(self.store.get_run("run-2"))

    def test_claim_run_rejects_second_active_run_for_same_task(self) -> None:
        first = self.store.claim_run(
            ClaimRequest(
                fingerprint="fingerprint-1",
                source_type="task.created",
                source_id="evt-1",
                owner="worker-a",
                run=make_run(run_id="run-1"),
            ),
            now="2026-04-05T12:00:00Z",
        )

        second = self.store.claim_run(
            ClaimRequest(
                fingerprint="fingerprint-2",
                source_type="task.updated",
                source_id="evt-2",
                owner="worker-b",
                run=make_run(run_id="run-2"),
            ),
            now="2026-04-05T12:00:01Z",
        )

        self.assertTrue(first.accepted)
        self.assertFalse(second.accepted)
        self.assertEqual("already_claimed", second.reason)
        self.assertEqual("run-1", second.existing_run.run_id)

    def test_transition_status_updates_run_and_releases_lock_on_terminal_state(self) -> None:
        outcome = self.store.claim_run(
            ClaimRequest(
                fingerprint="fingerprint-1",
                source_type="task.created",
                source_id="evt-1",
                owner="worker-a",
                run=make_run(),
            ),
            now="2026-04-05T12:00:00Z",
        )

        planning = self.store.transition_status(
            outcome.run.run_id,
            to_status="planning",
            expected_from="claimed",
            updated_at="2026-04-05T12:01:00Z",
        )
        completed = self.store.transition_status(
            outcome.run.run_id,
            to_status="failed",
            expected_from="planning",
            updated_at="2026-04-05T12:02:00Z",
            last_error="bad payload",
        )
        reacquired = self.store.acquire_lock(
            outcome.run.task_key,
            run_id=outcome.run.run_id,
            owner="worker-b",
            acquired_at="2026-04-05T12:02:30Z",
        )

        self.assertEqual("planning", planning.status)
        self.assertEqual("failed", completed.status)
        self.assertEqual("bad payload", completed.last_error)
        self.assertTrue(reacquired.acquired)

        audit_events = [entry["event_type"] for entry in self.store.list_audit(outcome.run.run_id)]
        self.assertEqual(["run_claimed", "status_transition", "status_transition"], audit_events)

    def test_transition_status_rejects_invalid_flow(self) -> None:
        created_run = self.store.create_run(make_run())

        with self.assertRaises(StatusTransitionError):
            self.store.transition_status(
                created_run.run_id,
                to_status="opening_pr",
                expected_from="claimed",
                updated_at="2026-04-05T12:01:00Z",
            )

    def test_update_run_fields_and_lookup_by_pr_and_ci(self) -> None:
        created_run = self.store.create_run(make_run())
        updated = self.store.update_run_fields(
            created_run.run_id,
            session_id="session-updated",
            branch_name="ai/ado/AB#123/abc123",
            workspace_path="/tmp/run-1",
            pr_id="42",
            ci_run_id="99",
            chat_thread_id="chat-7",
            updated_at="2026-04-05T12:01:00Z",
        )

        self.assertEqual("42", updated.pr_id)
        self.assertEqual("99", updated.ci_run_id)
        self.assertEqual("session-updated", updated.session_id)
        self.assertEqual(updated, self.store.find_run_by_pr_id("42"))
        self.assertEqual(updated, self.store.find_run_by_ci_run_id("99"))


if __name__ == "__main__":
    unittest.main()
