import base64
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from src.core.models import EventBus
from src.plugins.manager import PluginManager, PluginManifest

def test_plugin_manager_loads_plugin(tmp_path: Path) -> None:
    """PluginManager should load a plugin after successful verification."""
    # Generate RSA key pair
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()
    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()

    # Create dummy plugin directory
    plugin_dir = tmp_path / "dummy_plugin"
    plugin_dir.mkdir()
    (plugin_dir / "dummy_plugin.py").write_text("def hello(): return 'world'")

    manifest_dict = {
        "name": "dummy_plugin",
        "version": "1.0",
        "public_key": public_pem,
    }
    (plugin_dir / "manifest.json").write_text(json.dumps(manifest_dict))

    # Sign the manifest
    signature = private_key.sign(
        json.dumps(manifest_dict, sort_keys=True).encode(),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )
    (plugin_dir / "manifest.sig").write_text(base64.b64encode(signature).decode())

    manager = PluginManager(EventBus())
    manager.load_plugin(plugin_dir)

    assert "dummy_plugin" in manager.loaded_plugins
    assert hasattr(manager.loaded_plugins["dummy_plugin"], "hello")
