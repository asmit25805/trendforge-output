import json
import yaml
import pytest
from pathlib import Path

from src.skills.registry import (
    SkillRegistry,
    SkillNotFound,
    DuplicateSkillError,
    load_skills_from_path,
)
from src.core.models import SkillSpec


@pytest.fixture
def empty_registry() -> SkillRegistry:
    """Provide a fresh SkillRegistry for each test."""
    return SkillRegistry()


def create_skill_manifest(
    base_path: Path,
    name: str,
    version: str,
    system_prompt: str = "You are a helper.",
    parameters: dict | None = None,
    ext: str = "json",
) -> Path:
    """Write a skill manifest file (JSON or YAML) and return its path."""
    parameters = parameters or {}
    data = {
        "name": name,
        "version": version,
        "description": f"Skill {name}",
        "system_prompt": system_prompt,
        "parameters": parameters,
    }
    file_path = base_path / f"{name}.{ext}"
    if ext == "json":
        file_path.write_text(json.dumps(data, indent=2))
    else:
        file_path.write_text(yaml.safe_dump(data))
    return file_path


def test_load_from_path_registers_multiple_skills(tmp_path: Path, empty_registry: SkillRegistry) -> None:
    """load_from_path should discover and register all supported manifests."""
    create_skill_manifest(tmp_path, "skill_a", "1.0.0")
    create_skill_manifest(tmp_path, "skill_b", "2.1.3", ext="yaml")
    empty_registry.load_from_path(tmp_path)
    specs = empty_registry.list_skills()
    assert len(specs) == 2
    names = {spec.name for spec in specs}
    assert names == {"skill_a", "skill_b"}


def test_resolve_returns_exact_spec(tmp_path: Path, empty_registry: SkillRegistry) -> None:
    """resolve must return the SkillSpec matching name and version."""
    create_skill_manifest(tmp_path, "my_skill", "0.2.5")
    empty_registry.load_from_path(tmp_path)
    spec = empty_registry.resolve("my_skill", "0.2.5")
    assert isinstance(spec, SkillSpec)
    assert spec.name == "my_skill"
    assert spec.version == "0.2.5"


def test_resolve_missing_raises_SkillNotFound(empty_registry: SkillRegistry) -> None:
    """Attempting to resolve an unknown skill should raise SkillNotFound."""
    with pytest.raises(SkillNotFound) as exc:
        empty_registry.resolve("nonexistent", "1.0.0")
    assert "Skill 'nonexistent' with version '1.0.0' not found." in str(exc.value)


def test_duplicate_skill_raises_DuplicateSkillError(tmp_path: Path, empty_registry: SkillRegistry) -> None:
    """Registering the same name‑version pair twice must raise DuplicateSkillError."""
    create_skill_manifest(tmp_path, "dup_skill", "1.0.0")
    empty_registry.load_from_path(tmp_path)
    spec = load_skills_from_path(tmp_path)[0]
    with pytest.raises(DuplicateSkillError) as exc:
        empty_registry.register(spec)
    assert "Skill 'dup_skill' version '1.0.0' is already registered." in str(exc.value)


def test_load_skills_from_path_parses_both_formats(tmp_path: Path) -> None:
    """load_skills_from_path should return SkillSpec objects for JSON and YAML manifests."""
    json_path = create_skill_manifest(tmp_path, "json_skill", "0.0.1")
    yaml_path = create_skill_manifest(tmp_path, "yaml_skill", "0.0.2", ext="yaml")
    specs = load_skills_from_path(tmp_path)
    assert len(specs) == 2
    spec_names = {spec.name for spec in specs}
    assert spec_names == {"json_skill", "yaml_skill"}
    # Verify that the correct versions are attached.
    versions = {spec.version for spec in specs}
    assert versions == {"0.0.1", "0.0.2"}


def test_register_and_resolve_directly(tmp_path: Path, empty_registry: SkillRegistry) -> None:
    """Manually registering a SkillSpec should make it resolvable without loading from path."""
    spec = SkillSpec(
        name="direct_skill",
        version="3.4.5",
        description="Directly created skill",
        system_prompt="Prompt for direct skill.",
        parameters={},
    )
    empty_registry.register(spec)
    resolved = empty_registry.resolve("direct_skill", "3.4.5")
    assert resolved is spec
    assert resolved.system_prompt == "Prompt for direct skill."


def test_load_from_path_ignores_unknown_extensions(tmp_path: Path, empty_registry: SkillRegistry) -> None:
    """Files with unsupported extensions should be ignored by load_from_path."""
    create_skill_manifest(tmp_path, "valid_skill", "1.0.0")
    # Create a stray file that should not be interpreted as a skill manifest.
    stray_file = tmp_path / "ignore.me"
    stray_file.write_text("not a manifest")
    empty_registry.load_from_path(tmp_path)
    specs = empty_registry.list_skills()
    assert len(specs) == 1
    assert specs[0].name == "valid_skill"


def test_list_skills_returns_all_registered(tmp_path: Path, empty_registry: SkillRegistry) -> None:
    """list_skills should return every skill that has been successfully registered."""
    create_skill_manifest(tmp_path, "alpha", "0.1.0")
    create_skill_manifest(tmp_path, "beta", "0.2.0")
    empty_registry.load_from_path(tmp_path)
    # Register an additional skill directly.
    extra = SkillSpec(
        name="gamma",
        version="0.3.0",
        description="Extra skill",
        system_prompt="Extra prompt",
        parameters={},
    )
    empty_registry.register(extra)
    all_specs = empty_registry.list_skills()
    names = {s.name for s in all_specs}
    assert names == {"alpha", "beta", "gamma"}
    versions = {s.version for s in all_specs}
    assert versions == {"0.1.0", "0.2.0", "0.3.0"}