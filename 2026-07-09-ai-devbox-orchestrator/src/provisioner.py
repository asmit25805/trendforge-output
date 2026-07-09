from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple

import docker
from docker.errors import APIError, NotFound

from src.core.models import BoxSpec, ProvisionError

logger = logging.getLogger(__name__)


def _spec_hash(spec: BoxSpec) -> str:
    """
    Deterministic hash of a BoxSpec used for naming resources.
    """
    # Convert the spec to a JSON string with sorted keys for reproducibility
    spec_dict: Dict[str, Any] = {
        "image": spec.image,
        "env": spec.env,
        "ports": spec.ports,
        "volumes": spec.volumes,
        "resources": spec.resources,
    }
    spec_json = json.dumps(spec_dict, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(spec_json.encode("utf-8")).hexdigest()[:12]


def _container_name(hash_: str) -> str:
    """
    Produce a Docker‑compatible container name from a hash.
    """
    return f"devbox_{hash_}"


@dataclass(frozen=True)
class ProvisionedBox:
    """
    Handle representing a running dev box.
    """

    container_id: str
    name: str
    spec: BoxSpec
    created_at: float

    @property
    def age_ms(self) -> int:
        """Milliseconds since the container was created."""
        return int((time.time() - self.created_at) * 1000)


class BoxProvisioner:
    """
    Translates a skill's BoxSpec into an isolated dev environment using Docker and guarantees idempotent provisioning.
    """

    def __init__(self, docker_client: docker.DockerClient | None = None) -> None:
        self.client = docker_client or docker.from_env()
        self._retry_attempts = 3
        self._base_backoff = 1.0  # seconds

    # --------------------------------------------------------------------- #
    # Public API
    # --------------------------------------------------------------------- #

    def provision(self, spec: BoxSpec) -> ProvisionedBox:
        """
        Create the container (or reuse an existing healthy one) and return a handle.
        """
        spec_hash = _spec_hash(spec)
        name = _container_name(spec_hash)

        if self.ensure_idempotent(name):
            container = self.client.containers.get(name)
            logger.info("Reusing existing container %s (id=%s)", name, container.id)
            return ProvisionedBox(
                container_id=container.id,
                name=name,
                spec=spec,
                created_at=container.attrs["Created"]
                if isinstance(container.attrs["Created"], float)
                else time.time(),
            )

        attempts = 0
        while attempts < self._retry_attempts:
            attempts += 1
            try:
                container = self._create_container(name, spec)
                logger.info(
                    "Provisioned new container %s (id=%s) on attempt %d",
                    name,
                    container.id,
                    attempts,
                )
                return ProvisionedBox(
                    container_id=container.id,
                    name=name,
                    spec=spec,
                    created_at=time.time(),
                )
            except (APIError, OSError) as exc:
                backoff = self._base_backoff * (2 ** (attempts - 1))
                logger.warning(
                    "Provisioning attempt %d for %s failed: %s – retrying in %.1f s",
                    attempts,
                    name,
                    exc,
                    backoff,
                )
                time.sleep(backoff)

        raise ProvisionError(spec_hash=spec_hash, attempts=attempts, last_error=exc)

    def ensure_idempotent(self, container_name: str) -> bool:
        """
        Return True if a container with ``container_name`` exists and is running.
        """
        try:
            container = self.client.containers.get(container_name)
            if container.status == "running":
                logger.debug("Container %s is already running", container_name)
                return True
            # If container exists but is not running, attempt to start it.
            logger.debug("Container %s exists but is %s; starting", container_name, container.status)
            container.start()
            return True
        except NotFound:
            logger.debug("Container %s not found; provisioning required", container_name)
            return False
        except APIError as exc:
            logger.error("Failed to inspect container %s: %s", container_name, exc)
            raise ProvisionError(spec_hash=container_name, attempts=1, last_error=exc)

    def destroy(self, container_name: str) -> None:
        """
        Stop and remove the container identified by ``container_name``.
        """
        try:
            container = self.client.containers.get(container_name)
            logger.info("Stopping container %s (id=%s)", container_name, container.id)
            container.stop()
            logger.info("Removing container %s", container_name)
            container.remove()
        except NotFound:
            logger.warning("Attempted to destroy non‑existent container %s", container_name)
        except APIError as exc:
            logger.error("Error while destroying container %s: %s", container_name, exc)
            raise ProvisionError(spec_hash=container_name, attempts=1, last_error=exc)

    # --------------------------------------------------------------------- #
    # Internal helpers
    # --------------------------------------------------------------------- #

    def _create_container(self, name: str, spec: BoxSpec) -> docker.models.containers.Container:
        """
        Low‑level Docker container creation respecting the BoxSpec.
        """
        ports = {f"{p}/tcp": p for p in spec.ports}
        binds = {
            f"{host_path}": {"bind": container_path, "mode": "rw"}
            for host_path, container_path in spec.volumes
        }

        host_config = self.client.api.create_host_config(
            port_bindings=ports,
            binds=binds,
            nano_cpus=int(spec.resources.get("cpu", 0) * 1e9) if spec.resources.get("cpu") else None,
            mem_limit=spec.resources.get("memory") if spec.resources.get("memory") else None,
        )

        container = self.client.api.create_container(
            image=spec.image,
            name=name,
            environment=spec.env,
            host_config=host_config,
            detach=True,
        )
        self.client.api.start(container=container["Id"])
        # Retrieve the high‑level container object for convenience
        return self.client.containers.get(container["Id"])