import os
import json
import re
import logging
from typing import List, Tuple, Callable, Dict, Any, Optional

from src.core.models import (
    _open_secure,
    _read_secure,
    _logger,
    register_hook,
    Hook,
)

# --------------------------------------------------------------------------- #
# Redaction rule handling
# --------------------------------------------------------------------------- #

# Built‑in default patterns. They are deliberately simple but effective.
_DEFAULT_RULES: List[Tuple[str, str]] = [
    # API keys / tokens (alphanumeric strings of length >= 20)
    ("api_key", r"[A-Za-z0-9]{20,}"),
    # Bearer tokens in HTTP headers
    ("bearer_token", r"Bearer\s+[A-Za-z0-9\-\._~+/]+=*"),
    # File system paths (Unix & Windows)
    ("unix_path", r"/(?:[^\\\s]+/)*[^\\\s]+"),
    ("windows_path", r"[A-Za-z]:\\(?:[^\\\s]+\\)*[^\\\s]+"),
    # Email‑like strings (avoid false positives on normal text)
    ("email", r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
]

# Configuration file name – users may place this anywhere up the directory tree.
_CONFIG_FILENAME = "redaction_rules.json"

# --------------------------------------------------------------------------- #
# Helper utilities
# --------------------------------------------------------------------------- #


def _discover_config(start_dir: str) -> Optional[str]:
    """
    Walk upwards from ``start_dir`` looking for a JSON file named
    ``_CONFIG_FILENAME``. Returns the absolute path if found, otherwise ``None``.
    """
    current = os.path.abspath(start_dir)
    root = os.path.abspath(os.sep)

    while True:
        candidate = os.path.join(current, _CONFIG_FILENAME)
        if os.path.isfile(candidate):
            return candidate
        if current == root:
            break
        current = os.path.dirname(current)
    return None


def _load_rules_from_file(path: str) -> List[Tuple[str, str]]:
    """
    Load redaction rules from a JSON file. The file must contain a list of
    objects with ``name`` and ``pattern`` keys. Returns a list of (name, pattern)
    tuples. Errors are logged and the function falls back to the built‑in defaults.
    """
    try:
        fd = _open_secure(path, os.O_RDONLY)
        try:
            raw = os.read(fd, 8192)
            # Continue reading until EOF
            while True:
                chunk = os.read(fd, 8192)
                if not chunk:
                    break
                raw += chunk
        finally:
            os.close(fd)

        data = json.loads(raw.decode())
        if not isinstance(data, list):
            raise ValueError("Redaction config must be a list")
        loaded: List[Tuple[str, str]] = []
        for entry in data:
            if not isinstance(entry, dict):
                continue
            name = entry.get("name")
            pattern = entry.get("pattern")
            if isinstance(name, str) and isinstance(pattern, str):
                loaded.append((name, pattern))
        return loaded
    except Exception as exc:  # pragma: no cover – exercised via tests
        _logger.error("Failed to load redaction config %s: %s", path, exc)
        return []


def _compile_rules(rules: List[Tuple[str, str]]) -> List[Tuple[str, re.Pattern]]:
    """
    Compile regex patterns. Invalid patterns are skipped with a logged warning.
    """
    compiled: List[Tuple[str, re.Pattern]] = []
    for name, pattern in rules:
        try:
            compiled.append((name, re.compile(pattern, re.IGNORECASE)))
        except re.error as exc:
            _logger.error("Invalid regex for rule %s: %s", name, exc)
    return compiled


# --------------------------------------------------------------------------- #
# Redactor implementation
# --------------------------------------------------------------------------- #


class Redactor:
    """
    Stateless utility that redacts secrets from raw transcript text using a set
    of regex rules. The class loads rules once at construction time and reuses
    compiled patterns for every call to :meth:`redact`.
    """

    def __init__(self, config_dir: Optional[str] = None) -> None:
        """
        Initialise the redactor.

        Parameters
        ----------
        config_dir:
            Directory from which to start the search for a ``redaction_rules.json``
            file. If ``None`` the current working directory is used.
        """
        start = config_dir or os.getcwd()
        config_path = _discover_config(start)

        # Load user‑provided rules; fall back to defaults if none are found.
        user_rules = _load_rules_from_file(config_path) if config_path else []
        all_rules = user_rules if user_rules else _DEFAULT_RULES

        self._rules: List[Tuple[str, re.Pattern]] = _compile_rules(all_rules)

        # Register internal hooks so external plugins can observe the process.
        register_hook("pre_redact", self._pre_hook)   # type: ignore[arg-type]
        register_hook("post_redact", self._post_hook)  # type: ignore[arg-type]

    # --------------------------------------------------------------------- #
    # Hook infrastructure
    # --------------------------------------------------------------------- #

    def _pre_hook(self, text: str) -> str:
        """
        Hook called before redaction. Allows external plugins to modify the raw
        input. The default implementation returns the text unchanged.
        """
        return text

    def _post_hook(self, original: str, redacted: str) -> str:
        """
        Hook called after redaction. Allows external plugins to post‑process the
        result. The default implementation returns the redacted text unchanged.
        """
        return redacted

    # --------------------------------------------------------------------- #
    # Public API
    # --------------------------------------------------------------------- #

    def redact(self, text: str) -> str:
        """
        Apply all active redaction patterns to ``text`` and return a safe version.
        Errors in individual patterns do not abort the whole operation; the
        original line is returned for that pattern and the incident is logged.
        """
        # Run pre‑redact hooks – they may return a modified string.
        try:
            for hook in _registry_get("pre_redact"):
                text = hook(text)  # type: ignore[call-arg]
        except Exception as exc:  # pragma: no cover
            _logger.error("Pre‑redact hook failed: %s", exc)

        redacted = text
        for name, pattern in self._rules:
            try:
                redacted = pattern.sub("[REDACTED]", redacted)
            except Exception as exc:
                # Log the failure but keep the original text for this rule.
                _logger.error("Redaction error on rule %s: %s", name, exc)
                redacted = text  # revert to original for safety

        # Run post‑redact hooks.
        try:
            for hook in _registry_get("post_redact"):
                redacted = hook(text, redacted)  # type: ignore[call-arg]
        except Exception as exc:  # pragma: no cover
            _logger.error("Post‑redact hook failed: %s", exc)

        return redacted

    # --------------------------------------------------------------------- #
    # Dynamic rule management
    # --------------------------------------------------------------------- #

    def add_rule(self, name: str, pattern: str) -> None:
        """
        Add a new redaction rule at runtime. The pattern is compiled immediately;
        invalid regex strings raise a ``ValueError``.
        """
        try:
            compiled = re.compile(pattern, re.IGNORECASE)
        except re.error as exc:
            raise ValueError(f"Invalid regex pattern for rule {name!r}: {exc}") from exc
        self._rules.append((name, compiled))

    def get_rules(self) -> List[Tuple[str, str]]:
        """
        Return the current set of rule definitions as ``(name, pattern)`` tuples.
        """
        return [(name, pat.pattern) for name, pat in self._rules]


# --------------------------------------------------------------------------- #
# Internal helper to retrieve hooks from the global registry.
# --------------------------------------------------------------------------- #


def _registry_get(event: str) -> List[Hook]:
    """
    Retrieve a list of registered hooks for ``event``. If the event does not
    exist, an empty list is returned. This helper isolates direct access to the
    global ``registry`` dictionary defined in ``src.core.models``.
    """
    from src.core.models import _registry as _global_registry  # type: ignore[attr-defined]

    return _global_registry.get(event, [])


# --------------------------------------------------------------------------- #
# Exported symbols
# --------------------------------------------------------------------------- #

__all__ = ["Redactor"]