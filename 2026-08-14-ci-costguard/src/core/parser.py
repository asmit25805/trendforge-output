from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, Iterator, Set, Type

from src.core.models import TokenRecord

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Registry infrastructure
# ---------------------------------------------------------------------------

_registry: Dict[str, Type["ProviderParser"]] = {}


class ProviderParser(ABC):
    """Abstract base class for all provider‑specific parsers.

    Sub‑classes must declare a ``supported_extensions`` attribute – a set of file
    extensions (including the leading dot) that the parser can handle – and implement
    the :meth:`parse` method which yields :class:`TokenRecord` objects.
    """

    supported_extensions: Set[str] = set()

    @abstractmethod
    def parse(self, path: Path) -> Iterator[TokenRecord]:
        """Yield :class:`TokenRecord` objects from *path*.

        Implementations should raise a ``ValueError`` if the file cannot be parsed.
        """
        raise NotImplementedError


def register_parser(cls: Type[ProviderParser]) -> Type[ProviderParser]:
    """Class decorator that registers a :class:`ProviderParser` implementation.

    The class must define a non‑empty ``supported_extensions`` attribute. The
    decorator adds the class to the internal ``_registry`` mapping keyed by each
    supported extension.
    """

    if not getattr(cls, "supported_extensions", None):
        raise ValueError("Parser must define a non‑empty 'supported_extensions' set")

    for ext in cls.supported_extensions:
        if ext in _registry:
            logger.warning("Overriding existing parser for extension %s", ext)
        _registry[ext] = cls
        logger.debug("Registered parser %s for extension %s", cls.__name__, ext)
    return cls


def parse_file(path: Path) -> Iterator[TokenRecord]:
    """Parse *path* using the appropriate registered parser.

    The function selects a parser based on the file's suffix. If no parser is
    registered for the suffix, a ``ValueError`` is raised.
    """

    ext = path.suffix.lower()
    parser_cls = _registry.get(ext)
    if parser_cls is None:
        raise ValueError(f"No parser registered for extension '{ext}'")
    parser = parser_cls()
    logger.info("Parsing %s with %s", path, parser_cls.__name__)
    return parser.parse(path)


__all__ = ["ProviderParser", "register_parser", "parse_file", "_registry"]
