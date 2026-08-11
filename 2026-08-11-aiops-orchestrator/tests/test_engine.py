import json
from pathlib import Path

import pytest

from src.core.engine import Engine

@pytest.mark.asyncio
async def test_engine_loads_config_successful(tmp_path: Path) -> None:
    """Engine should correctly load a valid JSON configuration file."""
    config = {"plugins": []}
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config))

    engine = Engine(config_path)
    loaded = engine.load_config()
    assert loaded == config
