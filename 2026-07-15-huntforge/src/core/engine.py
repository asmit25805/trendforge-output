import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Dict, List

from loguru import logger

from src.core.models import (
    HuntConfig,
    HuntReport,
    Target,
    Finding,
    ExploitArtifact,
    Verdict,
    ReportBundle,
)

from src.plugins.llm_provider import LLMProviderPlugin
from src.modules.recon import BaseReconModule
from src.modules.exploit import BaseExploitModule
from src.reporting.report import ReportGenerator


class Orchestrator:
    """Coordinates the hunt workflow.

    The orchestrator loads the configuration, runs the selected recon modules,
    feeds the findings to exploit modules, collects verdicts, and finally
    generates a signed report bundle.
    """

    def __init__(self, llm_provider: LLMProviderPlugin):
        self.llm_provider = llm_provider
        self.logger = logger

    async def _run_recon(self, config: Dict[str, Any], target: Target) -> List[Finding]:
        findings: List[Finding] = []
        for module_cfg in config.get("modules", []):
            module_name = module_cfg["name"]
            module_class = self._resolve_recon_module(module_name)
            module_instance: BaseReconModule = module_class(**module_cfg.get("config", {}))
            self.logger.info(f"Running recon module {module_name} on {target.hostname}")
            result = await module_instance.execute(target)
            findings.extend(result)
        return findings

    async def _run_exploit(self, config: Dict[str, Any], findings: List[Finding], target: Target) -> List[ExploitArtifact]:
        artifacts: List[ExploitArtifact] = []
        for module_cfg in config.get("modules", []):
            module_name = module_cfg["name"]
            module_class = self._resolve_exploit_module(module_name)
            module_instance: BaseExploitModule = module_class(**module_cfg.get("config", {}), llm_provider=self.llm_provider)
            self.logger.info(f"Running exploit module {module_name}")
            result = await module_instance.execute(findings, target)
            artifacts.extend(result)
        return artifacts

    async def _run_verdicts(self, artifacts: List[ExploitArtifact]) -> List[Verdict]:
        # Simple placeholder implementation – in a real system each artifact would be
        # executed in an isolated sandbox and its result turned into a Verdict.
        return [Verdict(success=True, details="Executed successfully") for _ in artifacts]

    def _resolve_recon_module(self, name: str) -> type[BaseReconModule]:
        from src.modules.recon import PortScanReconModule, SubdomainReconModule
        mapping = {
            "PortScanReconModule": PortScanReconModule,
            "SubdomainReconModule": SubdomainReconModule,
        }
        if name not in mapping:
            raise ValueError(f"Unknown recon module: {name}")
        return mapping[name]

    def _resolve_exploit_module(self, name: str) -> type[BaseExploitModule]:
        from src.modules.exploit import TemplateExploitModule
        mapping = {
            "TemplateExploitModule": TemplateExploitModule,
        }
        if name not in mapping:
            raise ValueError(f"Unknown exploit module: {name}")
        return mapping[name]

    async def run_hunt(self, config: HuntConfig) -> ReportBundle:
        """Execute a full hunt based on the supplied configuration.

        Returns a :class:`ReportBundle` containing the generated report and an optional
        cryptographic signature.
        """
        target = config.target
        recon_cfg = config.recon
        exploit_cfg = config.exploit

        findings = await self._run_recon(recon_cfg, target)
        artifacts = await self._run_exploit(exploit_cfg, findings, target)
        verdicts = await self._run_verdicts(artifacts)

        report = HuntReport(
            target=target,
            findings=findings,
            exploits=artifacts,
            verdicts=verdicts,
        )
        generator = ReportGenerator()
        bundle = generator.generate(report)
        return bundle


# Convenience function for the CLI entry‑point
def run_hunt(config_path: str, llm_provider: LLMProviderPlugin) -> ReportBundle:
    """Load a YAML configuration file and execute the hunt.

    Parameters
    ----------
    config_path: str
        Path to a YAML file describing the hunt.
    llm_provider: LLMProviderPlugin
        An instantiated LLM provider.
    """
    import yaml

    with open(config_path, "r", encoding="utf-8") as f:
        raw_cfg = yaml.safe_load(f)
    hunt_cfg = HuntConfig(**raw_cfg)
    orchestrator = Orchestrator(llm_provider)
    return asyncio.run(orchestrator.run_hunt(hunt_cfg))
