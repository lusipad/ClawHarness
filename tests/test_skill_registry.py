from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from harness_runtime.skill_registry import SkillRegistry


class SkillRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.registry_path = Path(self.temp_dir.name) / "registry.json"
        self.registry_path.write_text(
            json.dumps(
                {
                    "version": "2026-04-06",
                    "skills": [
                        {
                            "id": "analyze-task",
                            "version": "1.0.0",
                            "source": "openclaw-plugin/skills/analyze-task",
                            "description": "Analyze a task before execution.",
                            "instructions": ["Break down the task.", "List risks."],
                            "run_kinds": ["task"],
                            "agent_roles": ["planner"],
                            "provider_types": ["*"],
                        }
                    ],
                }
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


if __name__ == "__main__":
    unittest.main()
