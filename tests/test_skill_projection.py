from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from harness_runtime.skill_projection import project_openclaw_skills


class SkillProjectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_root = Path(self.temp_dir.name)

        source_root = self.repo_root / "skills" / "core" / "analyze-task"
        source_root.mkdir(parents=True, exist_ok=True)
        (source_root / "SKILL.md").write_text("# analyze-task\n", encoding="utf-8")
        (source_root / "README.md").write_text("canonical readme\n", encoding="utf-8")

        registry_path = self.repo_root / "skills" / "core" / "registry.json"
        registry_path.parent.mkdir(parents=True, exist_ok=True)
        registry_path.write_text(
            json.dumps(
                {
                    "version": "2026-04-09",
                    "skills": [
                        {
                            "id": "analyze-task",
                            "version": "1.0.0",
                            "source": "skills/core/analyze-task",
                            "description": "Analyze a task before execution.",
                            "instructions": ["Break down the task."],
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

    def test_project_openclaw_skills_rewrites_registry_and_copies_skill_files(self) -> None:
        registry_path = project_openclaw_skills(self.repo_root)

        self.assertEqual(self.repo_root / "openclaw-plugin" / "skills" / "registry.json", registry_path)
        payload = json.loads(registry_path.read_text(encoding="utf-8"))
        self.assertEqual("2026-04-09", payload["version"])
        self.assertEqual("openclaw-plugin/skills/analyze-task", payload["skills"][0]["source"])
        self.assertEqual(
            "# analyze-task\n",
            (self.repo_root / "openclaw-plugin" / "skills" / "analyze-task" / "SKILL.md").read_text(encoding="utf-8"),
        )
        self.assertEqual(
            "canonical readme\n",
            (self.repo_root / "openclaw-plugin" / "skills" / "analyze-task" / "README.md").read_text(
                encoding="utf-8"
            ),
        )

    def test_project_openclaw_skills_replaces_stale_target_entries(self) -> None:
        stale_root = self.repo_root / "openclaw-plugin" / "skills" / "stale-skill"
        stale_root.mkdir(parents=True, exist_ok=True)
        (stale_root / "SKILL.md").write_text("stale\n", encoding="utf-8")

        project_openclaw_skills(self.repo_root)

        self.assertFalse(stale_root.exists())


if __name__ == "__main__":
    unittest.main()
