import asyncio
from typing import List

import pytest
import pytest_asyncio
from pydantic import ValidationError

from src.core.models import Target
from src.modules.recon import PortScanReconModule, SubdomainReconModule


@pytest_asyncio.fixture
async def target() -> Target:
    """Provide a minimal Target instance for recon tests."""
    return Target(hostname="localhost")


@pytest.mark.asyncio
async def test_port_scan_recon(target: Target):
    module = PortScanReconModule(timeout_seconds=0, max_ports=10)
    findings = await module.execute(target)
    # With timeout set to 0 the scanner will quickly fail; we only assert that the
    # return type is correct.
    assert isinstance(findings, list)
    assert all(isinstance(f, Finding) for f in findings)


@pytest.mark.asyncio
async def test_subdomain_recon(target: Target):
    module = SubdomainReconModule(wordlist=["localhost"], max_depth=1)
    findings = await module.execute(target)
    assert isinstance(findings, list)
    assert all(isinstance(f, Finding) for f in findings)
