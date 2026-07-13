import json
import logging
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from . import __name__ as package_name
from ..core.engine import SkillEngine
from ..core.models import IllustrationRequest, IllustrationResult, QAReport

logger = logging.getLogger(package_name)
handler = logging.StreamHandler()
formatter = logging.Formatter(
    "%(asctime)s %(levelname)s %(name)s %(message)s", "%Y-%m-%d %H:%M:%S"
)
handler.setFormatter(formatter)
logger.addHandler(handler)
logger.setLevel(logging.INFO)

# The agents package can expose higher‑level orchestration helpers if needed.
