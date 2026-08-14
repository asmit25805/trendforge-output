from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Iterable, List

from src.core.models import AlertMessage

__all__ = ["AlertDispatcher", "AlertMessage"]

logger = logging.getLogger(__name__)


class AlertDispatcher:
    """Dispatches :class:`AlertMessage` objects to configured back‑ends.

    For the purpose of this library the default implementation simply logs the
    alert. Users can subclass ``AlertDispatcher`` and override ``dispatch`` to
    integrate with Slack, email, GitHub comments, etc.
    """

    def __init__(self, workers: int = 4) -> None:
        self._executor = ThreadPoolExecutor(max_workers=workers)
        logger.debug("AlertDispatcher initialized with %s workers", workers)

    def dispatch(self, message: AlertMessage) -> None:
        """Send *message* to all configured back‑ends.

        The base implementation logs the alert. Sub‑classes may provide richer
        behaviour.
        """
        logger.info("Dispatching alert – %s: %s", message.severity.upper(), message.title)
        logger.debug("Alert body: %s", message.body)

    def close(self) -> None:
        """Shut down the internal thread pool gracefully."""
        self._executor.shutdown(wait=True)
        logger.debug("AlertDispatcher thread pool shut down")
