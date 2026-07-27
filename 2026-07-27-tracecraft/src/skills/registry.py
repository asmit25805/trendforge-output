from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Dict, List, Tuple

import yaml

from src.core.models import SkillSpec

log = logging.getLogger(__name__)
log.setLevel(logging.INFO)


class SkillNotFound(RuntimeError):
    """Raised when a requested skill version cannot be found in the registry."""

    pass


class DuplicateSkillError(RuntimeError):
    """Raised when attempting to register a skill that already exists with the same version."""

    pass


class SkillRegistry:
    """In‑memory registry for :class:`SkillSpec` objects.

    The registry stores skills keyed by a tuple ``(name, version)``.  It provides
    methods to add a skill, retrieve a skill, and list all registered skills.
    """

    def __init__(self) -> None:
        self._skills: Dict[Tuple[str, str], SkillSpec] = {}

    def add_skill(self, spec: SkillSpec) -> None:
        key = (spec.name, spec.version)
        if key in self._skills:
            raise DuplicateSkillError(f"Skill {spec.name}@{spec.version} already registered")
        self._skills[key] = spec
        log.info("Registered skill %s@%s", spec.name, spec.version)

    def get_skill(self, name: str, version: str) -> SkillSpec:
        key = (name, version)
        try:
            return self._skills[key]
        except KeyError as exc:
            raise SkillNotFound(f"Skill {name}@{version} not found") from exc

    def list_skills(self) -> List[SkillSpec]:
        return list(self._skills.values())


def load_skills_from_path(path: str | os.PathLike) -> SkillRegistry:
    """Load skill manifests (JSON or YAML) from a directory into a ``SkillRegistry``.

    Parameters
    ----------
    path: str or PathLike
        Directory containing ``*.json`` or ``*.yaml`` files describing skills.
    """
    registry = SkillRegistry()
    base_path = Path(path)
    if not base_path.is_dir():
        raise NotADirectoryError(f"{path} is not a directory")

    for file_path in base_path.iterdir():
        if file_path.suffix.lower() not in {".json", ".yaml", ".yml"}:
            continue
        try:
            if file_path.suffix.lower() == ".json":
                data = json.load(file_path.open())
            else:
                data = yaml.safe_load(file_path.open())
            spec = SkillSpec(**data)
            registry.add_skill(spec)
        except Exception as exc:
            log.error("Failed to load skill from %s: %s", file_path, exc)
            raise exc
    return registry
