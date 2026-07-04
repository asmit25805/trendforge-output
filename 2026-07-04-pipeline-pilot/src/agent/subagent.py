from __future__ import annotations

import logging
from typing import Optional

from src.core.engine import Session, SessionManager
from src.core.models import Message

logger = logging.getLogger(__name__)


class SubAgent:
    """Runs an isolated sub‑task in its own :class:`Session`.

    The parent ``SessionManager`` is shared so that tool configuration and
    reflection behaviour stay consistent across sub‑agents.
    """

    def __init__(self, manager: SessionManager, task: str, *, initial_message: Optional[Message] = None):
        """Create a new ``SubAgent``.

        Parameters
        ----------
        manager:
            The ``SessionManager`` that will create the underlying ``Session``.
        task:
            A short description of the sub‑task the agent should perform.
        initial_message:
            Optional first message to seed the session. If omitted a generic
            user message containing ``task`` is created.
        """
        self.manager = manager
        self.task = task
        self.session: Session = manager.create_session()
        if initial_message is None:
            initial_message = Message(role="user", content=task)
        self.session.add_message(initial_message)
        logger.debug("SubAgent created for task '%s' with initial message %s", task, initial_message)

    def run(self) -> Message:
        """Execute the sub‑task and return the assistant's final reply."""
        logger.info("Running SubAgent for task: %s", self.task)
        return self.session.run()
