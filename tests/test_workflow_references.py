from __future__ import annotations

import unittest
from pathlib import Path


class WorkflowReferenceTests(unittest.TestCase):
    def test_flows_use_reference_fields_instead_of_inline_uses(self) -> None:
        flow_paths = [
            Path("openclaw-plugin/flows/task-run.yaml"),
            Path("openclaw-plugin/flows/pr-feedback.yaml"),
            Path("openclaw-plugin/flows/ci-recovery.yaml"),
        ]

        for flow_path in flow_paths:
            text = flow_path.read_text(encoding="utf-8")
            self.assertIn("skill_refs:", text, msg=f"{flow_path} should declare skill_refs")
            self.assertIn("capability_refs:", text, msg=f"{flow_path} should declare capability_refs")
            self.assertNotIn("\nskills:\n", text, msg=f"{flow_path} should not declare legacy skills list")
            self.assertNotIn("\nuses:", text, msg=f"{flow_path} should not use inline uses fields")

    def test_skill_steps_reference_skill_ids_and_capability_steps_reference_capability_ids(self) -> None:
        expectations = {
            "openclaw-plugin/flows/task-run.yaml": ["skill_id: analyze-task", "capability_id: task.get"],
            "openclaw-plugin/flows/pr-feedback.yaml": ["skill_id: fix-pr-feedback", "capability_id: pr.list_comments"],
            "openclaw-plugin/flows/ci-recovery.yaml": ["skill_id: recover-ci-failure", "capability_id: ci.get_status"],
        }

        for relative_path, required_fragments in expectations.items():
            text = Path(relative_path).read_text(encoding="utf-8")
            for fragment in required_fragments:
                self.assertIn(fragment, text, msg=f"{relative_path} is missing `{fragment}`")


if __name__ == "__main__":
    unittest.main()
