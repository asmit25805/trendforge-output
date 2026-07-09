import pathlib
import shutil
import textwrap

import pytest

from src.core.models import SkillLoadError, SkillMeta
from src.registry import SkillRegistry


@pytest.fixture
def temp_skill_dir(tmp_path: pathlib.Path) -> pathlib.Path:
    """
    Create a temporary directory with a valid SKILL.md file.
    """
    skill_dir = tmp_path / "skill_a"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        textwrap.dedent(
            """
            ---
            name: skill_a
            description: A simple test skill
            user_invocable: true
            script_path: script_a.sh
            metadata:
              box_spec:
                image: python:3.12-slim
            ---
            # Skill A
            """
        ).strip()
    )
    # Create a dummy script file referenced by the skill
    (skill_dir / "script_a.sh").write_text("#!/bin/sh\necho Hello")
    return tmp_path


def test_load_skills_parses_valid_skill(temp_skill_dir: pathlib.Path) -> None:
    registry = SkillRegistry()
    skills = registry.load_skills(str(temp_skill_dir))
    assert len(skills) == 1
    meta = skills[0]
    assert isinstance(meta, SkillMeta)
    assert meta.name == "skill_a"
    assert meta.description == "A simple test skill"
    assert meta.user_invocable is True
    assert meta.script_path == "script_a.sh"
    assert isinstance(meta.metadata, dict)
    assert "box_spec" in meta.metadata
    assert meta.metadata["box_spec"]["image"] == "python:3.12-slim"


def test_get_skill_returns_correct_instance(temp_skill_dir: pathlib.Path) -> None:
    registry = SkillRegistry()
    registry.load_skills(str(temp_skill_dir))
    meta = registry.get_skill("skill_a")
    assert meta is not None
    assert meta.name == "skill_a"
    # Ensure the returned object is the same cached instance
    assert registry.get_skill("skill_a") is meta


def test_duplicate_skill_name_overrides(temp_skill_dir: pathlib.Path) -> None:
    # Create a second skill with the same name but different description
    dup_dir = temp_skill_dir / "dup"
    dup_dir.mkdir()
    (dup_dir / "SKILL.md").write_text(
        textwrap.dedent(
            """
            ---
            name: skill_a
            description: Overridden description
            user_invocable: false
            script_path: script_dup.sh
            metadata: {}
            ---
            """
        ).strip()
    )
    (dup_dir / "script_dup.sh").write_text("#!/bin/sh\necho Duplicate")
    registry = SkillRegistry()
    skills = registry.load_skills(str(temp_skill_dir))
    # The registry should contain the overridden definition
    meta = registry.get_skill("skill_a")
    assert meta is not None
    assert meta.description == "Overridden description"
    assert meta.user_invocable is False
    assert meta.script_path == "script_dup.sh"
    # Ensure only one skill is cached despite two files
    assert len(skills) == 2
    assert len(registry._skills) == 1  # internal cache reflects override


def test_load_skills_raises_skillloaderror_on_missing_required_field(temp_skill_dir: pathlib.Path) -> None:
    # Create a malformed skill missing the required 'script_path'
    bad_dir = temp_skill_dir / "bad"
    bad_dir.mkdir()
    (bad_dir / "SKILL.md").write_text(
        textwrap.dedent(
            """
            ---
            name: bad_skill
            description: Missing script_path
            user_invocable: true
            metadata: {}
            ---
            """
        ).strip()
    )
    registry = SkillRegistry()
    with pytest.raises(SkillLoadError) as excinfo:
        registry.load_skills(str(temp_skill_dir))
    assert excinfo.value.path == "SKILL.md"
    # The error message should mention the missing field
    assert "script_path" in excinfo.value.message


def test_load_skills_raises_skillloaderror_line_info(temp_skill_dir: pathlib.Path) -> None:
    # Create a skill with invalid YAML syntax on line 3
    bad_yaml_dir = temp_skill_dir / "bad_yaml"
    bad_yaml_dir.mkdir()
    (bad_yaml_dir / "SKILL.md").write_text(
        textwrap.dedent(
            """
            ---
            name: bad_yaml_skill
            description Invalid YAML line
            user_invocable: true
            script_path: script.sh
            metadata: {}
            ---
            """
        ).strip()
    )
    registry = SkillRegistry()
    with pytest.raises(SkillLoadError) as excinfo:
        registry.load_skills(str(temp_skill_dir))
    err = excinfo.value
    # The parser should report the line where YAML broke (line 3 in this case)
    assert err.line == 3
    assert "YAML" in err.message or "parsing" in err.message


def test_reload_updates_skills(temp_skill_dir: pathlib.Path) -> None:
    registry = SkillRegistry()
    registry.load_skills(str(temp_skill_dir))
    assert registry.get_skill("skill_a") is not None
    # Add a new skill after initial load
    new_dir = temp_skill_dir / "new_skill"
    new_dir.mkdir()
    (new_dir / "SKILL.md").write_text(
        textwrap.dedent(
            """
            ---
            name: new_skill
            description: Added after initial load
            user_invocable: true
            script_path: new_script.sh
            metadata: {}
            ---
            """
        ).strip()
    )
    (new_dir / "new_script.sh").write_text("#!/bin/sh\necho New")
    # Reload should pick up the new definition
    registry.reload()
    new_meta = registry.get_skill("new_skill")
    assert new_meta is not None
    assert new_meta.name == "new_skill"
    assert new_meta.description == "Added after initial load"
    # Ensure original skill is still present
    assert registry.get_skill("skill_a") is not None
```