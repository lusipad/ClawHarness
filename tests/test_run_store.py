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

    def test_awaiting_human_can_resume_into_review_ci_and_pr_stages(self) -> None:
        targets = ("awaiting_review", "awaiting_ci", "opening_pr")

        for index, target in enumerate(targets, start=1):
            run = self.store.create_run(
                make_run(run_id=f"run-resume-{index}", task_key=f"AB#{300 + index}", status="awaiting_human")
            )
            resumed = self.store.transition_status(
                run.run_id,
                to_status=target,
                expected_from="awaiting_human",
                updated_at=f"2026-04-05T12:0{index}:00Z",
            )
            self.assertEqual(target, resumed.status)

    def test_thread_links_can_be_created_and_replaced(self) -> None:
        first = self.store.create_run(make_run(run_id="run-thread-1", task_key="AB#401", status="awaiting_review"))
        second = self.store.create_run(make_run(run_id="run-thread-2", task_key="AB#402", status="coding"))

        self.store.link_thread(
            "room-1",
            run_id=first.run_id,
            session_id=first.session_id,
            provider_type="rocketchat",
            linked_at="2026-04-05T12:20:00Z",
        )
        initial = self.store.get_thread_link("room-1")

        self.store.link_thread(
            "room-1",
            run_id=second.run_id,
            session_id=second.session_id,
            provider_type="rocketchat",
            linked_at="2026-04-05T12:21:00Z",
        )
        replaced = self.store.get_thread_link("room-1")

        self.assertEqual(first.run_id, initial["run_id"])
        self.assertEqual("2026-04-05T12:20:00Z", initial["linked_at"])
        self.assertEqual(second.run_id, replaced["run_id"])
        self.assertEqual(second.session_id, replaced["session_id"])
        self.assertEqual("2026-04-05T12:21:00Z", replaced["linked_at"])

    def test_list_runs_returns_latest_first_and_filters_by_status(self) -> None:
        first = self.store.create_run(
            make_run(run_id="run-1", task_key="AB#1", status="claimed").normalized(timestamp="2026-04-05T12:00:00Z")
        )
        second = self.store.create_run(
            make_run(run_id="run-2", task_key="AB#2", status="claimed").normalized(timestamp="2026-04-05T12:05:00Z")
        )
        self.store.transition_status(
            first.run_id,
            to_status="planning",
            expected_from="claimed",
            updated_at="2026-04-05T12:10:00Z",
        )
        claimed_runs = self.store.list_runs(status="claimed", limit=10)
        all_runs = self.store.list_runs(limit=10)
        filtered_runs = self.store.list_runs(status="planning", task_key="AB#1", limit=10)

        self.assertEqual(["run-2"], [run.run_id for run in claimed_runs])
        self.assertEqual(["run-1", "run-2"], [run.run_id for run in all_runs])
        self.assertEqual(["run-1"], [run.run_id for run in filtered_runs])

    def test_summarize_runs_counts_active_and_terminal_statuses(self) -> None:
        self.store.create_run(make_run(run_id="run-1", task_key="AB#1", status="claimed"))
        self.store.create_run(make_run(run_id="run-2", task_key="AB#2", status="awaiting_review"))
        self.store.create_run(make_run(run_id="run-3", task_key="AB#3", status="failed"))

        summary = self.store.summarize_runs()

        self.assertEqual(3, summary["total_runs"])
        self.assertEqual(2, summary["active_runs"])
        self.assertEqual(1, summary["terminal_runs"])
        self.assertEqual(1, summary["status_counts"]["claimed"])
        self.assertEqual(1, summary["status_counts"]["awaiting_review"])
        self.assertEqual(1, summary["status_counts"]["failed"])

    def test_run_graph_primitives_store_parent_child_checkpoints_and_artifacts(self) -> None:
        parent = self.store.create_run(make_run(run_id="run-parent", task_key="AB#201", status="awaiting_review"))
        child = self.store.create_run(make_run(run_id="run-child", task_key="AB#201-review", status="coding"))

        self.store.link_runs(parent.run_id, child.run_id, relation_type="review-follow-up", created_at="2026-04-05T12:15:00Z")
        self.store.record_checkpoint(
            parent.run_id,
            "workspace_prepared",
            payload={"workspace_path": "/tmp/run-parent"},
            created_at="2026-04-05T12:16:00Z",
        )
        self.store.record_artifact(
            parent.run_id,
            "executor_result",
            "task-result.json",
            path="/tmp/task-result.json",
            payload={"status": "completed"},
            created_at="2026-04-05T12:17:00Z",
        )
        self.store.record_skill_selection(
            child.run_id,
            parent_run_id=parent.run_id,
            run_kind="task",
            agent_role="executor",
            registry_version="2026-04-06",
            selection_key="task:executor:azure-devops",
            payload={"matched_skills": [{"skill_id": "implement-task"}]},
            created_at="2026-04-05T12:18:00Z",
        )

        self.assertEqual(parent, self.store.get_parent_run(child.run_id))
        self.assertEqual(["run-child"], [run.run_id for run in self.store.list_child_runs(parent.run_id)])
        parent_relation = self.store.get_parent_relationship(child.run_id)
        self.assertEqual("review-follow-up", parent_relation["relation_type"])
        self.assertEqual("run-parent", parent_relation["run"].run_id)
        child_relationships = self.store.list_child_relationships(parent.run_id)
        self.assertEqual("review-follow-up", child_relationships[0]["relation_type"])
        self.assertEqual("run-child", child_relationships[0]["run"].run_id)
        self.assertEqual("workspace_prepared", self.store.list_checkpoints(parent.run_id)[0]["stage"])
        self.assertEqual("executor_result", self.store.list_artifacts(parent.run_id)[0]["artifact_type"])
        selections = self.store.list_skill_selections(child.run_id)
        self.assertEqual("task", selections[0]["run_kind"])
        self.assertEqual("executor", selections[0]["agent_role"])
        self.assertIn("implement-task", selections[0]["payload_json"])

    def test_cleanup_candidates_and_workspace_usage_queries(self) -> None:
        archived = self.store.create_run(
            make_run(run_id="run-old", task_key="AB#301", status="completed").normalized(timestamp="2026-04-01T12:00:00Z")
        )
        active = self.store.create_run(
            make_run(run_id="run-live", task_key="AB#302", status="coding").normalized(timestamp="2026-04-06T12:00:00Z")
        )
        self.store.update_run_fields(
            archived.run_id,
            workspace_path=str(Path(self.temp_dir.name) / "workspaces" / "run-old"),
            updated_at="2026-04-01T12:00:00Z",
        )
        self.store.update_run_fields(
            active.run_id,
            workspace_path=str(Path(self.temp_dir.name) / "workspaces" / "run-live"),
            updated_at="2026-04-06T12:00:00Z",
        )

        candidates = self.store.list_cleanup_candidates(older_than="2026-04-03T00:00:00Z", limit=10)

        self.assertEqual(["run-old"], [run.run_id for run in candidates])
        self.assertFalse(
            self.store.has_active_run_for_workspace(str(Path(self.temp_dir.name) / "workspaces" / "run-old"))
        )
        self.assertTrue(
            self.store.has_active_run_for_workspace(str(Path(self.temp_dir.name) / "workspaces" / "run-live"))
        )


if __name__ == "__main__":
    unittest.main()
