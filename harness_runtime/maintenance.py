from __future__ import annotations

import shutil
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from run_store import RunStore

from .config import HarnessRuntimeConfig


@dataclass(frozen=True)
class MaintenanceResult:
    retention_days: int
    scanned_runs: int
    cleaned_runs: int
    deleted_workspaces: int
    pruned_runtime_state: bool
    run_results: list[dict[str, object]]

    def to_payload(self) -> dict[str, object]:
        return asdict(self)


class RunMaintenanceService:
    def __init__(self, *, config: HarnessRuntimeConfig, store: RunStore):
        self.config = config
        self.store = store

    def cleanup_terminal_runs(
        self,
        *,
        retention_days: int | None = None,
        limit: int | None = None,
        now: str | None = None,
    ) -> MaintenanceResult:
        effective_retention_days = retention_days or self.config.runtime.terminal_run_retention_days
        effective_limit = limit or self.config.runtime.cleanup_batch_size
        stamp = now or _utc_now()
        self.store.cleanup_expired_state(now=stamp)

        cutoff_dt = _parse_timestamp(stamp) - timedelta(days=effective_retention_days)
        cutoff = cutoff_dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")
        candidates = self.store.list_cleanup_candidates(older_than=cutoff, limit=effective_limit)
        workspace_root = Path(self.config.runtime.workspace_root).resolve()

        cleaned_runs = 0
        deleted_workspaces = 0
        results: list[dict[str, object]] = []
        for run in candidates:
            outcome = self._cleanup_run(run.run_id, workspace_root=workspace_root)
            if outcome["status"] == "cleaned":
                cleaned_runs += 1
            if outcome["workspace_deleted"]:
                deleted_workspaces += 1
            results.append(outcome)

        return MaintenanceResult(
            retention_days=effective_retention_days,
            scanned_runs=len(candidates),
            cleaned_runs=cleaned_runs,
            deleted_workspaces=deleted_workspaces,
            pruned_runtime_state=True,
            run_results=results,
        )

    def _cleanup_run(self, run_id: str, *, workspace_root: Path) -> dict[str, object]:
        run = self.store.get_run(run_id)
        if run is None:
            return {"run_id": run_id, "status": "skipped", "reason": "run_not_found", "workspace_deleted": False}

        if not run.workspace_path:
            self.store.append_audit(run.run_id, "maintenance_cleanup_skipped", payload={"reason": "missing_workspace_path"})
            return {
                "run_id": run.run_id,
                "status": "skipped",
                "reason": "missing_workspace_path",
                "workspace_deleted": False,
            }

        workspace = Path(run.workspace_path)
        if self.store.has_active_run_for_workspace(run.workspace_path, exclude_run_id=run.run_id):
            self.store.append_audit(
                run.run_id,
                "maintenance_cleanup_skipped",
                payload={"reason": "workspace_in_use", "workspace_path": run.workspace_path},
            )
            return {
                "run_id": run.run_id,
                "status": "skipped",
                "reason": "workspace_in_use",
                "workspace_deleted": False,
            }

        if not _is_within_root(workspace, workspace_root):
            self.store.append_audit(
                run.run_id,
                "maintenance_cleanup_skipped",
                payload={"reason": "workspace_outside_root", "workspace_path": run.workspace_path},
            )
            return {
                "run_id": run.run_id,
                "status": "skipped",
                "reason": "workspace_outside_root",
                "workspace_deleted": False,
            }

        if not workspace.exists():
            self.store.append_audit(
                run.run_id,
                "maintenance_cleanup_completed",
                payload={"workspace_deleted": False, "reason": "workspace_missing"},
            )
            return {
                "run_id": run.run_id,
                "status": "cleaned",
                "reason": "workspace_missing",
                "workspace_deleted": False,
            }

        shutil.rmtree(workspace)
        self.store.append_audit(
            run.run_id,
            "maintenance_cleanup_completed",
            payload={"workspace_deleted": True, "workspace_path": run.workspace_path},
        )
        return {
            "run_id": run.run_id,
            "status": "cleaned",
            "reason": "workspace_deleted",
            "workspace_deleted": True,
        }


def _is_within_root(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root)
        return True
    except ValueError:
        return False


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
