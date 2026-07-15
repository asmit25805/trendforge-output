import abc
import asyncio
import socket
from typing import List

from loguru import logger

from src.core.models import Finding, Target


class BaseReconModule(abc.ABC):
    """Abstract base for all reconnaissance primitives."""

    @abc.abstractmethod
    async def execute(self, target: Target) -> List[Finding]:
        """Run the module against *target* and return a list of :class:`Finding` objects."""
        raise NotImplementedError


class PortScanReconModule(BaseReconModule):
    """Very small TCP port scanner used for demonstration purposes.

    Parameters
    ----------
    timeout_seconds: int
        Socket timeout for each connection attempt.
    max_ports: int
        Upper bound for ports to scan (starting at 1).
    """

    def __init__(self, timeout_seconds: int = 3, max_ports: int = 1024):
        self.timeout = timeout_seconds
        self.max_ports = max_ports

    async def execute(self, target: Target) -> List[Finding]:
        logger.info("Scanning %s up to %d ports", target.hostname, self.max_ports)
        loop = asyncio.get_event_loop()
        findings: List[Finding] = []
        for port in range(1, self.max_ports + 1):
            try:
                await loop.run_in_executor(
                    None,
                    lambda: socket.create_connection((target.hostname, port), timeout=self.timeout),
                )
                findings.append(
                    Finding(
                        type="open_port",
                        description=f"Port {port} is open",
                        severity="low",
                        data={"port": port},
                    )
                )
            except OSError:
                continue
        return findings


class SubdomainReconModule(BaseReconModule):
    """Simple sub‑domain enumeration using a static wordlist.

    Parameters
    ----------
    wordlist: List[str] | str
        Either a list of words or the name of a built‑in wordlist.
    max_depth: int
        Not used in this stub but kept for API compatibility.
    """

    DEFAULT_WORDLIST = ["www", "api", "dev", "staging", "test"]

    def __init__(self, wordlist: str | List[str] = "default", max_depth: int = 1):
        if isinstance(wordlist, str) and wordlist == "default":
            self.wordlist = self.DEFAULT_WORDLIST
        elif isinstance(wordlist, list):
            self.wordlist = wordlist
        else:
            self.wordlist = [wordlist]
        self.max_depth = max_depth

    async def execute(self, target: Target) -> List[Finding]:
        logger.info("Enumerating subdomains for %s", target.hostname)
        findings: List[Finding] = []
        for prefix in self.wordlist:
            sub = f"{prefix}.{target.hostname}"
            try:
                socket.gethostbyname(sub)
                findings.append(
                    Finding(
                        type="subdomain",
                        description=f"Discovered subdomain {sub}",
                        severity="low",
                        data={"subdomain": sub},
                    )
                )
            except socket.gaierror:
                continue
        return findings
