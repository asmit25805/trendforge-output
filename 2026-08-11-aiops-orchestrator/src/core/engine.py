'''\
Engine module – orchestrates plugins, scheduler and event bus.
'''\

import json
import logging
import argparse
from pathlib import Path
from typing import Any, Mapping

from src.core.models import Event, EventBus, logger as core_logger
from src.plugins.manager import PluginManager
from src.scheduler.cron import Scheduler, CronJob


class Engine:
    """Main orchestrator engine.

    It loads a JSON configuration, initialises the plugin manager and the
    scheduler, and starts the event loop.
    """

    def __init__(self, config_path: Path) -> None:
        self.config_path = config_path
        self.event_bus = EventBus()
        self.plugin_manager = PluginManager(self.event_bus)
        self.scheduler = Scheduler(self.event_bus)

    def load_config(self) -> Mapping[str, Any]:
        """Load configuration from *self.config_path*.
        """
        with open(self.config_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def start(self) -> None:
        """Start engine components synchronously.
        """
        config = self.load_config()
        plugins = config.get("plugins", [])
        self.plugin_manager.load_plugins(plugins)
        # In a real implementation the scheduler would be started in an
        # asyncio task. For the purpose of this repository we keep it simple.
        core_logger.info("Engine started with %d plugins", len(plugins))


def main() -> None:
    """Command‑line entry point.
    """
    parser = argparse.ArgumentParser(description="Run aiops-orchestrator engine")
    parser.add_argument("config", type=Path, help="Path to JSON configuration file")
    args = parser.parse_args()

    engine = Engine(args.config)
    engine.start()


if __name__ == "__main__":
    main()
