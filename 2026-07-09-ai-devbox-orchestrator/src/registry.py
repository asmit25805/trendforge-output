from __future__ import annotations

import logging
import pathlib
from typing import Dict, List, Optional

import yaml

from src.core.models import SkillLoadError, SkillMeta

logger = logging.getLogger(__name__)


class SkillRegistry:
    """
    Discovers, parses, and validates skill definitions stored as markdown files with front‑matter,
    exposing them as first‑class objects to the engine.
    """

    def __init__(self) -> None:
        self._skills: Dict[str, SkillMeta] = {}
        self._root_path: Optional[pathlib.Path] = None

    # --------------------------------------------------------------------- #
    # Public API
    # --------------------------------------------------------------------- #

    def load_skills(self, root_path: str) -> List[SkillMeta]:
        """
        Walk ``root_path`` recursively, read each ``SKILL.md`` file, and return a list of
        validated :class:`SkillMeta` instances.  The internal cache is refreshed.
        """
        root = pathlib.Path(root_path).resolve()
        if not root.is_dir():
            raise ValueError(f"root_path must be a directory: {root_path}")

        self._root_path = root
        self._skills.clear()
        found: List[SkillMeta] = []

        for md_path in root.rglob("SKILL.md"):
            try:
                meta = self._parse_skill_file(md_path)
                if meta.name in self._skills:
                    logger.warning(
                        "Duplicate skill name %s found in %s; overriding previous definition",
                        meta.name,
                        md_path,
                    )
                self._skills[meta.name] = meta
                found.append(meta)
                logger.debug("Loaded skill %s from %s", meta.name, md_path)
            except SkillLoadError as exc:
                logger.error("Failed to load skill: %s", exc)
                raise

        return found

    def get_skill(self, name: str) -> Optional[SkillMeta]:
        """
        Fetch a skill by its unique name, returning ``None`` if the skill is not present.
        """
        return self._skills.get(name)

    def reload(self) -> None:
        """
        Re‑scan the previously supplied root directory to pick up new or updated skills
        without restarting the service.
        """
        if self._root_path is None:
            raise RuntimeError("SkillRegistry.reload() called before load_skills()")
        self.load_skills(str(self._root_path))

    # --------------------------------------------------------------------- #
    # Internal helpers
    # --------------------------------------------------------------------- #

    def _parse_skill_file(self, path: pathlib.Path) -> SkillMeta:
        """
        Parse a single markdown file that contains YAML front‑matter.  The front‑matter
        must define at least ``name``, ``description`` and ``script_path``.  Any parsing
        or validation error raises :class:`SkillLoadError` with an accurate line number.
        """
        try:
            content = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise SkillLoadError(path, 0, f"Unable to read file: {exc}") from exc

        # Front‑matter must be delimited by lines containing exactly three hyphens.
        # Example:
        # ---
        # yaml: ...
        # ---
        # markdown body...
        delimiter = "---"
        lines = content.splitlines()
        if not lines or lines[0].strip() != delimiter:
            raise SkillLoadError(path, 1, "Missing opening front‑matter delimiter '---'")

        try:
            end_index = lines[1:].index(delimiter) + 1
        except ValueError as exc:
            raise SkillLoadError(path, len(lines), "Missing closing front‑matter delimiter '---'") from exc

        yaml_block = "\n".join(lines[1:end_index])
        try:
            data = yaml.safe_load(yaml_block) or {}
        except yaml.YAMLError as exc:
            line = getattr(exc, "problem_mark", None)
            line_no = line.line + 1 if line else 1
            raise SkillLoadError(path, line_no, f"YAML parsing error: {exc}") from exc

        # Validate required fields
        required = ["name", "description", "script_path"]
        for field in required:
            if field not in data:
                raise SkillLoadError(path, 1, f"Missing required field '{field}' in front‑matter")

        # Normalise fields
        name = str(data["name"])
        description = str(data["description"])
        user_invocable = bool(data.get("user_invocable", False))
        script_path_raw = data["script_path"]
        script_path = pathlib.Path(str(script_path_raw)).as_posix()

        # Resolve script_path relative to the markdown file location
        script_abs = (path.parent / script_path).resolve()
        if not script_abs.is_file():
            raise SkillLoadError(
                path,
                1,
                f"script_path does not point to an existing file: {script_path}",
            )

        # Remaining keys become metadata; ensure it's a dict.
        metadata_raw = data.get("metadata", {})
        if not isinstance(metadata_raw, dict):
            raise SkillLoadError(
                path,
                1,
                "metadata field must be a mapping (dictionary) if present",
            )
        metadata = dict(metadata_raw)

        # Build the immutable SkillMeta instance
        skill_meta = SkillMeta(
            name=name,
            description=description,
            user_invocable=user_invocable,
            script_path=script_abs,
            metadata=metadata,
        )
        return skill_meta


__all__ = ["SkillRegistry", "SkillMeta"]