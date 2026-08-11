'''\
Plugin manager – loads and verifies plugins.
'''\

import base64
import importlib.util
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from src.core.models import EventBus, logger as core_logger


@dataclass
class PluginManifest:
    """Representation of a plugin manifest.

    *name* – module name of the plugin.
    *version* – semantic version string.
    *public_key* – PEM‑encoded RSA public key used for signature verification.
    """
    name: str
    version: str
    public_key: str  # PEM string


class PluginManager:
    """Handles dynamic loading of signed plugins.

    The manager verifies the RSA‑SHA256 signature of a plugin's manifest
    before importing the plugin module.
    """

    def __init__(self, event_bus: EventBus) -> None:
        self.event_bus = event_bus
        self.loaded_plugins: Dict[str, Any] = {}

    def verify_manifest(self, manifest: PluginManifest, signature: bytes) -> bool:
        """Verify the RSA‑SHA256 signature of *manifest*.
        """
        public_key = serialization.load_pem_public_key(manifest.public_key.encode())
        try:
            public_key.verify(
                signature,
                json.dumps(manifest.__dict__, sort_keys=True).encode(),
                padding.PKCS1v15(),
                hashes.SHA256(),
            )
            return True
        except Exception as exc:
            core_logger.error("Manifest verification failed: %s", exc)
            return False

    def load_plugin(self, plugin_path: Path) -> None:
        """Load a plugin from *plugin_path* after verification.
        """
        manifest_path = plugin_path / "manifest.json"
        signature_path = plugin_path / "manifest.sig"
        if not manifest_path.is_file() or not signature_path.is_file():
            raise FileNotFoundError("Missing manifest or signature files for plugin")

        manifest_data = json.loads(manifest_path.read_text())
        manifest = PluginManifest(**manifest_data)
        signature = base64.b64decode(signature_path.read_text())

        if not self.verify_manifest(manifest, signature):
            raise ValueError(f"Invalid signature for plugin {manifest.name}")

        module_file = plugin_path / f"{manifest.name}.py"
        spec = importlib.util.spec_from_file_location(manifest.name, module_file)
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot import plugin module {manifest.name}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.loaded_plugins[manifest.name] = module
        core_logger.info("Plugin %s loaded successfully", manifest.name)

    def load_plugins(self, plugin_dirs: list[Path]) -> None:
        """Convenience method to load multiple plugins.
        """
        for p in plugin_dirs:
            self.load_plugin(Path(p))
