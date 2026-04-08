from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from harness_runtime.skill_registry import (
    SkillRegistry,
    canonical_skill_registry_path,
    default_skill_registry_path,
    legacy_skill_registry_path,
    load_default_skill_registry,
)


class SkillRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_root = Path(self.temp_dir.name)
        self.registry_payload = {
            "version": "2026-04-06",
            "skills": [
                {
                    "id": "analyze-task",
                    "version": "1.0.0",
                    "source": "skills/core/analyze-task",
                    "description": "Analyze a task before execution.",
                    "instructions": ["Break down the task.", "List risks."],
                    "run_kinds": ["task"],
                    "agent_roles": ["planner"],
                    "provider_types": ["*"],
                }
            ],
        }
        self.registry_path = self.repo_root / "registry.json"
        self.registry_path.write_text(
            json.dumps(
                self.registry_payload
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_select_matches_skill_by_run_kind_and_role(self) -> None:
        registry = SkillRegistry.from_path(self.registry_path)

        selection = registry.select(run_kind="task", agent_role="planner", provider_type="github")

        self.assertEqual("2026-04-06", selection.registry_version)
        self.assertEqual(["analyze-task"], [item.skill_id for item in selection.matched_skills])
        self.assertFalse(selection.used_safe_default)

    def test_select_falls_back_to_safe_default_when_no_match(self) -> None:
        registry = SkillRegistry.from_path(self.registry_path)

        selection = registry.select(run_kind="ci-recovery", agent_role="executor", provider_type="github")

        self.assertTrue(selection.used_safe_default)
        self.assertEqual("no_matching_skill", selection.fallback_reason)
        self.assertEqual([], list(selection.matched_skills))

    def test_default_skill_registry_path_prefers_canonical_source(self) -> None:
        canonical_path = canonical_skill_registry_path(self.repo_root)
        canonical_path.parent.mkdir(parents=True, exist_ok=True)
        canonical_path.write_text(json.dumps(self.registry_payload), encoding="utf-8")

        legacy_path = legacy_skill_registry_path(self.repo_root)
        legacy_path.parent.mkdir(parents=True, exist_ok=True)
        legacy_path.write_text(json.dumps({"version": "legacy", "skills": []}), encoding="utf-8")

        self.assertEqual(canonical_path, default_skill_registry_path(self.repo_root))

    def test_default_skill_registry_path_falls_back_to_legacy_source(self) -> None:
        legacy_path = legacy_skill_registry_path(self.repo_root)
        legacy_path.parent.mkdir(parents=True, exist_ok=True)
        legacy_path.write_text(json.dumps(self.registry_payload), encoding="utf-8")

        self.assertEqual(legacy_path, default_skill_registry_path(self.repo_root))

    def test_load_default_skill_registry_reads_canonical_source(self) -> None:
        canonical_path = canonical_skill_registry_path(self.repo_root)
        canonical_path.parent.mkdir(parents=True, exist_ok=True)
        canonical_path.write_text(json.dumps(self.registry_payload), encoding="utf-8")

        registry = load_default_skill_registry(self.repo_root)

        self.assertEqual("2026-04-06", registry.registry_version)
        self.assertEqual(["analyze-task"], [item.skill_id for item in registry.definitions])

    def test_load_default_skill_registry_returns_missing_when_no_source_exists(self) -> None:
        registry = load_default_skill_registry(self.repo_root)

        self.assertEqual("missing", registry.registry_version)
        self.assertEqual((), registry.definitions)


if __name__ == "__main__":
    unittest.main()
