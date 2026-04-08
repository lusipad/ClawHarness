from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any, Mapping

from .skill_registry import canonical_skill_registry_path


GENERATED_SKILLS_README = """# OpenClaw Skill 兼容镜像

`openclaw-plugin/skills/` 是从 `skills/core/` 投影出来的兼容目录。

规则：

- 不要在这里手工维护 skill 真文。
- `openclaw-plugin/openclaw.plugin.json` 继续通过这里向 OpenClaw 暴露 skills。
- 变更 canonical source 后，重新运行 `python -m harness_runtime.skill_projection`。
- 在 CI 或发布前，可用 `python -m harness_runtime.skill_projection --check` 校验这里没有漂移。
"""


def project_openclaw_skills(
    repo_root: str | Path | None = None,
    *,
    target_root: str | Path | None = None,
) -> Path:
    root = _repo_root(repo_root)
    canonical_registry_path = canonical_skill_registry_path(root)
    if not canonical_registry_path.exists():
        raise FileNotFoundError(f"Canonical skill registry not found: {canonical_registry_path}")

    payload = json.loads(canonical_registry_path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("Canonical skill registry root must be a JSON object")
    skills = payload.get("skills")
    if not isinstance(skills, list):
        raise ValueError("Canonical skill registry is missing skills[]")

    projected_root = _projected_root(root, target_root)
    projected_root.mkdir(parents=True, exist_ok=True)
    _clear_directory(projected_root)

    projected_skills: list[dict[str, Any]] = []
    for raw_skill in skills:
        if not isinstance(raw_skill, Mapping):
            raise ValueError("Each canonical skill entry must be an object")
        skill = dict(raw_skill)
        skill_id = _require_string(skill, "id")
        source = _require_string(skill, "source")
        source_dir = root / source
        if not source_dir.exists():
            raise FileNotFoundError(f"Canonical skill directory not found: {source_dir}")
        destination_dir = projected_root / skill_id
        shutil.copytree(source_dir, destination_dir)

        projected_skill = dict(skill)
        projected_skill["source"] = f"openclaw-plugin/skills/{skill_id}"
        projected_skills.append(projected_skill)

    projected_payload = dict(payload)
    projected_payload["skills"] = projected_skills
    registry_path = projected_root / "registry.json"
    (projected_root / "README.md").write_text(GENERATED_SKILLS_README, encoding="utf-8", newline="\n")
    registry_path.write_text(json.dumps(projected_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return registry_path


def verify_openclaw_skill_projection(
    repo_root: str | Path | None = None,
    *,
    target_root: str | Path | None = None,
) -> Path:
    root = _repo_root(repo_root)
    projected_root = _projected_root(root, target_root)
    if not projected_root.exists():
        raise FileNotFoundError(f"Projected skill directory not found: {projected_root}")

    with tempfile.TemporaryDirectory() as temp_dir:
        expected_root = Path(temp_dir) / "openclaw-plugin" / "skills"
        project_openclaw_skills(root, target_root=expected_root)
        _assert_same_directory_contents(expected_root, projected_root)
    return projected_root / "registry.json"


def _clear_directory(directory: Path) -> None:
    for entry in directory.iterdir():
        if entry.is_dir():
            shutil.rmtree(entry)
            continue
        entry.unlink()


def _assert_same_directory_contents(expected_root: Path, actual_root: Path) -> None:
    expected_files = _collect_files(expected_root)
    actual_files = _collect_files(actual_root)
    if expected_files != actual_files:
        missing = sorted(expected_files - actual_files)
        extra = sorted(actual_files - expected_files)
        details: list[str] = []
        if missing:
            details.append(f"missing={missing}")
        if extra:
            details.append(f"extra={extra}")
        raise ValueError("Projected skill directory drift detected: " + ", ".join(details))

    for relative_path in sorted(expected_files):
        expected_bytes = (expected_root / relative_path).read_bytes()
        actual_bytes = (actual_root / relative_path).read_bytes()
        if expected_bytes != actual_bytes:
            raise ValueError(f"Projected skill file drift detected: {relative_path.as_posix()}")


def _collect_files(root: Path) -> set[Path]:
    return {
        path.relative_to(root)
        for path in root.rglob("*")
        if path.is_file()
    }


def _projected_root(root: Path, target_root: str | Path | None) -> Path:
    if target_root is not None:
        return Path(target_root)
    return root / "openclaw-plugin" / "skills"


def _repo_root(repo_root: str | Path | None) -> Path:
    if repo_root is not None:
        return Path(repo_root)
    return Path(__file__).resolve().parents[1]


def _require_string(mapping: Mapping[str, Any], key: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Expected non-empty string field: {key}")
    return value.strip()


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Project canonical ClawHarness skills into OpenClaw consumables")
    parser.add_argument("--repo-root", default=None, help="repository root that owns skills/core and openclaw-plugin/skills")
    parser.add_argument("--target-root", default=None, help="optional override for the projected OpenClaw skills directory")
    parser.add_argument("--check", action="store_true", help="verify that the projected skill directory matches the canonical source")
    return parser


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()
    if args.check:
        registry_path = verify_openclaw_skill_projection(repo_root=args.repo_root, target_root=args.target_root)
        print(f"projection_ok {registry_path}")
        return 0

    registry_path = project_openclaw_skills(repo_root=args.repo_root, target_root=args.target_root)
    print(f"projected_skills {registry_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
