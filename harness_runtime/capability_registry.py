from __future__ import annotations

import importlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from workflow_provider import WorkflowProviderClient

from .config import HarnessRuntimeConfig


CapabilityFactory = Callable[[HarnessRuntimeConfig], WorkflowProviderClient | None]


@dataclass(frozen=True)
class CapabilityDefinition:
    plugin_id: str
    plugin_version: str
    capability_type: str
    capability_id: str
    factory: str

    def load_factory(self) -> CapabilityFactory:
        module_name, separator, symbol_name = self.factory.partition(":")
        if not separator or not module_name or not symbol_name:
            raise CapabilityRegistryError(f"Invalid capability factory path: {self.factory}")
        module = importlib.import_module(module_name)
        factory = getattr(module, symbol_name, None)
        if not callable(factory):
            raise CapabilityRegistryError(f"Capability factory is not callable: {self.factory}")
        return factory


class CapabilityRegistryError(ValueError):
    pass


class CapabilityRegistry:
    def __init__(self, definitions: tuple[CapabilityDefinition, ...]):
        self.definitions = definitions

    @classmethod
    def from_path(cls, path: str | Path) -> "CapabilityRegistry":
        manifest_path = Path(path)
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise CapabilityRegistryError(f"Failed to read capability manifest: {manifest_path}") from exc
        except json.JSONDecodeError as exc:
            raise CapabilityRegistryError(f"Failed to parse capability manifest: {manifest_path}") from exc
        return cls.from_payload(payload)

    @classmethod
    def from_payload(cls, payload: Any) -> "CapabilityRegistry":
        if not isinstance(payload, Mapping):
            raise CapabilityRegistryError("Capability manifest root must be a JSON object")
        plugin_id = _require_string(payload, "id")
        plugin_version = _require_string(payload, "version")
        capabilities = payload.get("capabilities")
        if not isinstance(capabilities, list):
            raise CapabilityRegistryError("Capability manifest is missing capabilities[]")

        definitions: list[CapabilityDefinition] = []
        for item in capabilities:
            if not isinstance(item, Mapping):
                raise CapabilityRegistryError("Each capability entry must be an object")
            definitions.append(
                CapabilityDefinition(
                    plugin_id=plugin_id,
                    plugin_version=plugin_version,
                    capability_type=_require_string(item, "type"),
                    capability_id=_require_string(item, "id"),
                    factory=_require_string(item, "factory"),
                )
            )
        return cls(tuple(definitions))

    def capabilities_for(self, capability_type: str) -> tuple[CapabilityDefinition, ...]:
        normalized = capability_type.strip().lower()
        return tuple(item for item in self.definitions if item.capability_type.strip().lower() == normalized)

    def instantiate_task_providers(self, config: HarnessRuntimeConfig) -> dict[str, WorkflowProviderClient]:
        providers: dict[str, WorkflowProviderClient] = {}
        for definition in self.capabilities_for("task-provider"):
            instance = definition.load_factory()(config)
            if instance is None:
                continue
            providers[definition.capability_id] = instance
        return providers


def default_capability_manifest_path(repo_root: str | Path | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else Path(__file__).resolve().parent
    return root / "capabilities" / "builtin-task-providers.json"


def load_default_capability_registry(repo_root: str | Path | None = None) -> CapabilityRegistry:
    return CapabilityRegistry.from_path(default_capability_manifest_path(repo_root))


def _require_string(mapping: Mapping[str, Any], key: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise CapabilityRegistryError(f"Capability manifest field must be a non-empty string: {key}")
    return value.strip()
