from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


@dataclass(frozen=True)
class SkillDefinition:
    skill_id: str
    version: str
    source: str
    description: str
    instructions: tuple[str, ...]
    run_kinds: tuple[str, ...]
    agent_roles: tuple[str, ...]
    provider_types: tuple[str, ...]

    def matches(self, *, run_kind: str, agent_role: str, provider_type: str) -> bool:
        return (
            self._matches_value(run_kind, self.run_kinds)
            and self._matches_value(agent_role, self.agent_roles)
            and self._matches_value(provider_type, self.provider_types)
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "version": self.version,
            "source": self.source,
            "description": self.description,
            "instructions": list(self.instructions),
            "run_kinds": list(self.run_kinds),
            "agent_roles": list(self.agent_roles),
            "provider_types": list(self.provider_types),
        }

    def _matches_value(self, value: str, candidates: tuple[str, ...]) -> bool:
        normalized = value.strip().lower()
        return "*" in candidates or normalized in candidates


@dataclass(frozen=True)
class SkillSelection:
    registry_version: str
    run_kind: str
    agent_role: str
    provider_type: str
    matched_skills: tuple[SkillDefinition, ...]
    selection_reason: str
    fallback_reason: str | None = None

    @property
    def used_safe_default(self) -> bool:
        return not self.matched_skills

    def to_payload(self) -> dict[str, Any]:
        return {
            "registry_version": self.registry_version,
            "run_kind": self.run_kind,
            "agent_role": self.agent_role,
            "provider_type": self.provider_type,
            "selection_reason": self.selection_reason,
            "fallback_reason": self.fallback_reason,
            "used_safe_default": self.used_safe_default,
            "matched_skills": [skill.to_payload() for skill in self.matched_skills],
        }


class SkillRegistryError(ValueError):
    pass


class SkillRegistry:
    def __init__(self, *, registry_version: str, definitions: tuple[SkillDefinition, ...]):
        self.registry_version = registry_version
        self.definitions = definitions

    @classmethod
    def from_path(cls, path: str | Path) -> "SkillRegistry":
        registry_path = Path(path)
        try:
            payload = json.loads(registry_path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise SkillRegistryError(f"Failed to read skill registry: {registry_path}") from exc
        except json.JSONDecodeError as exc:
            raise SkillRegistryError(f"Failed to parse skill registry: {registry_path}") from exc

        if not isinstance(payload, Mapping):
            raise SkillRegistryError("Skill registry root must be a JSON object")
        version = payload.get("version")
        if not isinstance(version, str) or not version.strip():
            raise SkillRegistryError("Skill registry is missing version")
        skills = payload.get("skills")
        if not isinstance(skills, list):
            raise SkillRegistryError("Skill registry is missing skills[]")

        definitions: list[SkillDefinition] = []
        for item in skills:
            if not isinstance(item, Mapping):
                raise SkillRegistryError("Each skill entry must be an object")
            definitions.append(
                SkillDefinition(
                    skill_id=_require_string(item, "id"),
                    version=_require_string(item, "version"),
                    source=_require_string(item, "source"),
                    description=_require_string(item, "description"),
                    instructions=_require_string_list(item, "instructions"),
                    run_kinds=_normalize_string_list(item, "run_kinds"),
                    agent_roles=_normalize_string_list(item, "agent_roles"),
                    provider_types=_normalize_string_list(item, "provider_types"),
                )
            )
        return cls(registry_version=version.strip(), definitions=tuple(definitions))

    def select(
        self,
        *,
        run_kind: str,
        agent_role: str,
        provider_type: str,
        task_context: Mapping[str, Any] | None = None,
    ) -> SkillSelection:
        del task_context
        matched = tuple(
            definition
            for definition in self.definitions
            if definition.matches(
                run_kind=run_kind,
                agent_role=agent_role,
                provider_type=provider_type,
            )
        )
        if matched:
            return SkillSelection(
                registry_version=self.registry_version,
                run_kind=run_kind,
                agent_role=agent_role,
                provider_type=provider_type,
                matched_skills=matched,
                selection_reason=(
                    f"Matched {len(matched)} skill(s) for run_kind={run_kind}, "
                    f"agent_role={agent_role}, provider_type={provider_type}."
                ),
            )
        return SkillSelection(
            registry_version=self.registry_version,
            run_kind=run_kind,
            agent_role=agent_role,
            provider_type=provider_type,
            matched_skills=(),
            selection_reason="No specialized skill matched; using the safe default execution path.",
            fallback_reason="no_matching_skill",
        )


def canonical_skill_registry_path(repo_root: str | Path | None = None) -> Path:
    root = _repo_root(repo_root)
    return root / "skills" / "core" / "registry.json"


def legacy_skill_registry_path(repo_root: str | Path | None = None) -> Path:
    root = _repo_root(repo_root)
    return root / "openclaw-plugin" / "skills" / "registry.json"


def candidate_skill_registry_paths(repo_root: str | Path | None = None) -> tuple[Path, ...]:
    return (
        canonical_skill_registry_path(repo_root),
        legacy_skill_registry_path(repo_root),
    )


def default_skill_registry_path(repo_root: str | Path | None = None) -> Path:
    for candidate in candidate_skill_registry_paths(repo_root):
        if candidate.exists():
            return candidate
    return canonical_skill_registry_path(repo_root)


def load_default_skill_registry(repo_root: str | Path | None = None) -> SkillRegistry:
    path = default_skill_registry_path(repo_root)
    if not path.exists():
        return SkillRegistry(registry_version="missing", definitions=())
    return SkillRegistry.from_path(path)


def _repo_root(repo_root: str | Path | None) -> Path:
    if repo_root is not None:
        return Path(repo_root)
    return Path(__file__).resolve().parents[1]


def _require_string(mapping: Mapping[str, Any], key: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise SkillRegistryError(f"Skill registry field must be a non-empty string: {key}")
    return value.strip()


def _require_string_list(mapping: Mapping[str, Any], key: str) -> tuple[str, ...]:
    values = mapping.get(key)
    if not isinstance(values, list) or not values:
        raise SkillRegistryError(f"Skill registry field must be a non-empty string array: {key}")
    result: list[str] = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise SkillRegistryError(f"Skill registry array contains invalid string: {key}")
        result.append(value.strip())
    return tuple(result)


def _normalize_string_list(mapping: Mapping[str, Any], key: str) -> tuple[str, ...]:
    values = _require_string_list(mapping, key)
    return tuple(value.lower() for value in values)
