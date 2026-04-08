from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Mapping

from .skill_registry import canonical_skill_registry_path


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

    projected_root = Path(target_root) if target_root is not None else root / "openclaw-plugin" / "skills"
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
    registry_path.write_text(json.dumps(projected_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return registry_path


def _clear_directory(directory: Path) -> None:
    for entry in directory.iterdir():
        if entry.is_dir():
            shutil.rmtree(entry)
            continue
        entry.unlink()


def _repo_root(repo_root: str | Path | None) -> Path:
    if repo_root is not None:
        return Path(repo_root)
    return Path(__file__).resolve().parents[1]


def _require_string(mapping: Mapping[str, Any], key: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Expected non-empty string field: {key}")
    return value.strip()
