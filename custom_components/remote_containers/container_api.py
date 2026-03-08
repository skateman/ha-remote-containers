"""Container API abstraction for Docker and Podman."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from .connection import SSHConnection, SSHConnectionError
from .const import (
    CONF_CONTAINER_LABEL,
    CONF_RUNTIME,
    CONTAINER_STATE_RUNNING,
    DEFAULT_CONTAINER_LABEL,
    RUNTIME_AUTO,
    RUNTIME_DOCKER,
    RUNTIME_PODMAN,
)

_LOGGER = logging.getLogger(__name__)


@dataclass
class ContainerInfo:
    """Container information."""

    container_id: str
    name: str
    image: str
    image_id: str
    status: str
    state: str
    created: str
    ports: dict[str, Any]
    labels: dict[str, str]

    @property
    def is_running(self) -> bool:
        """Return True if container is running."""
        return self.state.lower() == CONTAINER_STATE_RUNNING

    @property
    def image_name(self) -> str:
        """Return image name without tag."""
        return self.image.split(":")[0] if ":" in self.image else self.image

    @property
    def image_tag(self) -> str:
        """Return image tag."""
        return self.image.split(":")[-1] if ":" in self.image else "latest"


@dataclass
class ImageInfo:
    """Container image information."""

    image_id: str
    repository: str
    tag: str
    digest: str | None
    created: str
    size: int


class ContainerAPIError(Exception):
    """Exception raised when container API operations fail."""


class ContainerAPI:
    """Abstraction layer for Docker/Podman container operations."""

    def __init__(
        self,
        connection: SSHConnection,
        config: dict[str, Any],
    ) -> None:
        """Initialize the container API."""
        self._connection = connection
        self._label_filter = config.get(CONF_CONTAINER_LABEL, DEFAULT_CONTAINER_LABEL)
        self._runtime_config = config.get(CONF_RUNTIME, RUNTIME_AUTO)
        self._runtime: str | None = None

    @property
    def runtime(self) -> str:
        """Return the detected or configured runtime."""
        if self._runtime is None:
            return self._runtime_config
        return self._runtime

    async def async_detect_runtime(self) -> str:
        """Detect which container runtime is available."""
        if self._runtime_config != RUNTIME_AUTO:
            self._runtime = self._runtime_config
            return self._runtime

        # Try Docker first
        stdout, stderr, returncode = await self._connection.async_run_command(
            "docker --version"
        )
        if returncode == 0 and "docker" in stdout.lower():
            self._runtime = RUNTIME_DOCKER
            _LOGGER.info("Detected container runtime: Docker")
            return self._runtime

        # Try Podman
        stdout, stderr, returncode = await self._connection.async_run_command(
            "podman --version"
        )
        if returncode == 0 and "podman" in stdout.lower():
            self._runtime = RUNTIME_PODMAN
            _LOGGER.info("Detected container runtime: Podman")
            return self._runtime

        raise ContainerAPIError("No container runtime (Docker/Podman) detected")

    def _cmd(self, command: str) -> str:
        """Build command with appropriate runtime."""
        runtime = self._runtime or "docker"
        return f"{runtime} {command}"

    async def async_list_containers(self) -> list[ContainerInfo]:
        """List all managed containers."""
        if self._runtime is None:
            await self.async_detect_runtime()

        # Use JSON format for reliable parsing
        cmd = self._cmd(
            f'ps -a --filter "label={self._label_filter}" '
            '--format "{{json .}}"'
        )

        stdout, stderr, returncode = await self._connection.async_run_command(cmd)

        if returncode != 0:
            _LOGGER.error("Failed to list containers: %s", stderr)
            raise ContainerAPIError(f"Failed to list containers: {stderr}")

        containers = []
        for line in stdout.strip().split("\n"):
            if not line:
                continue
            try:
                data = json.loads(line)
                container = await self._parse_container_info(data)
                if container:
                    containers.append(container)
            except json.JSONDecodeError as err:
                _LOGGER.warning("Failed to parse container JSON: %s", err)
                continue

        return containers

    async def _parse_container_info(self, data: dict[str, Any]) -> ContainerInfo | None:
        """Parse container info from docker/podman JSON output."""
        try:
            # Get detailed inspect data for more info
            container_id = data.get("ID") or data.get("Id", "")
            if not container_id:
                return None

            inspect_data = await self._inspect_container(container_id)

            # Get image from inspect Config.Image (preserves tag even when tag updated)
            # Fall back to docker ps Image field
            image = inspect_data.get("Config", {}).get("Image") or data.get("Image", "")

            # Get image ID and normalize (strip sha256: prefix)
            raw_image_id = inspect_data.get("Image", "")
            if raw_image_id.startswith("sha256:"):
                raw_image_id = raw_image_id[7:]
            image_id = raw_image_id[:12] if raw_image_id else ""

            return ContainerInfo(
                container_id=container_id[:12],
                name=data.get("Names", "").strip("/").split(",")[0],
                image=image,
                image_id=image_id,
                status=data.get("Status", ""),
                state=data.get("State", inspect_data.get("State", {}).get("Status", "unknown")),
                created=data.get("CreatedAt", ""),
                ports=self._parse_ports(data.get("Ports", "")),
                labels=inspect_data.get("Config", {}).get("Labels", {}),
            )
        except Exception as err:
            _LOGGER.warning("Failed to parse container info: %s", err)
            return None

    async def _inspect_container(self, container_id: str) -> dict[str, Any]:
        """Get detailed container information."""
        cmd = self._cmd(f"inspect {container_id}")
        stdout, stderr, returncode = await self._connection.async_run_command(cmd)

        if returncode != 0:
            return {}

        try:
            data = json.loads(stdout)
            return data[0] if isinstance(data, list) and data else {}
        except json.JSONDecodeError:
            return {}

    def _parse_ports(self, ports_str: str) -> dict[str, Any]:
        """Parse ports string into dict."""
        if not ports_str:
            return {}

        ports = {}
        # Parse format like "0.0.0.0:8080->80/tcp"
        for port_mapping in ports_str.split(","):
            port_mapping = port_mapping.strip()
            if "->" in port_mapping:
                match = re.match(r"([\d.]+)?:?(\d+)->(\d+)/(\w+)", port_mapping)
                if match:
                    host_ip, host_port, container_port, proto = match.groups()
                    ports[f"{container_port}/{proto}"] = {
                        "HostIp": host_ip or "0.0.0.0",
                        "HostPort": host_port,
                    }
        return ports

    async def async_start_container(self, container_id: str) -> bool:
        """Start a container."""
        cmd = self._cmd(f"start {container_id}")
        stdout, stderr, returncode = await self._connection.async_run_command(cmd)

        if returncode != 0:
            _LOGGER.error("Failed to start container %s: %s", container_id, stderr)
            raise ContainerAPIError(f"Failed to start container: {stderr}")

        _LOGGER.info("Started container %s", container_id)
        return True

    async def async_stop_container(self, container_id: str) -> bool:
        """Stop a container."""
        cmd = self._cmd(f"stop {container_id}")
        stdout, stderr, returncode = await self._connection.async_run_command(cmd)

        if returncode != 0:
            _LOGGER.error("Failed to stop container %s: %s", container_id, stderr)
            raise ContainerAPIError(f"Failed to stop container: {stderr}")

        _LOGGER.info("Stopped container %s", container_id)
        return True

    async def async_restart_container(self, container_id: str) -> bool:
        """Restart a container."""
        cmd = self._cmd(f"restart {container_id}")
        stdout, stderr, returncode = await self._connection.async_run_command(cmd)

        if returncode != 0:
            _LOGGER.error("Failed to restart container %s: %s", container_id, stderr)
            raise ContainerAPIError(f"Failed to restart container: {stderr}")

        _LOGGER.info("Restarted container %s", container_id)
        return True

    async def async_recreate_container(self, container_id: str, new_image: str) -> str:
        """Recreate a container with a new image.

        Captures the current container config, removes it, and creates a new one.
        Preserves the running state (if it was running, start it; if stopped, leave stopped).

        Returns:
            New container ID
        """
        # Get current container config
        inspect_data = await self._inspect_container(container_id)
        if not inspect_data:
            raise ContainerAPIError(f"Cannot get config for container {container_id}")

        config = inspect_data.get("Config", {})
        host_config = inspect_data.get("HostConfig", {})
        name = inspect_data.get("Name", "").lstrip("/")
        
        # Check if container was running before we stop it
        state = inspect_data.get("State", {})
        was_running = state.get("Running", False) or state.get("Status", "").lower() == "running"

        if not name:
            raise ContainerAPIError("Container has no name, cannot recreate")

        # Stop the container (if running)
        if was_running:
            await self.async_stop_container(container_id)

        # Remove the container
        cmd = self._cmd(f"rm {container_id}")
        stdout, stderr, returncode = await self._connection.async_run_command(cmd)
        if returncode != 0:
            raise ContainerAPIError(f"Failed to remove container: {stderr}")

        # Build new container command - use 'create' instead of 'run -d'
        cmd_parts = ["create", f"--name {name}"]

        # Restore labels
        labels = config.get("Labels", {})
        for key, value in labels.items():
            cmd_parts.append(f'--label "{key}={value}"')

        # Restore environment variables (skip common image defaults)
        # These are typically set by base images and shouldn't be preserved
        skip_env_prefixes = ("PATH", "HOME", "HOSTNAME", "TERM")
        env = config.get("Env", [])
        for env_var in env:
            if "=" in env_var:
                key = env_var.split("=")[0]
                if not key.startswith(skip_env_prefixes):
                    cmd_parts.append(f'-e "{env_var}"')

        # Restore port bindings
        port_bindings = host_config.get("PortBindings", {})
        for container_port, host_bindings in port_bindings.items():
            if host_bindings:
                for binding in host_bindings:
                    host_ip = binding.get("HostIp", "")
                    host_port = binding.get("HostPort", "")
                    if host_ip and host_ip != "0.0.0.0":
                        cmd_parts.append(f"-p {host_ip}:{host_port}:{container_port.split('/')[0]}")
                    elif host_port:
                        cmd_parts.append(f"-p {host_port}:{container_port.split('/')[0]}")

        # Restore volume mounts
        mounts = host_config.get("Binds", [])
        for mount in mounts or []:
            cmd_parts.append(f'-v "{mount}"')

        # Restore tmpfs mounts
        tmpfs = host_config.get("Tmpfs", {})
        for path, options in (tmpfs or {}).items():
            if options:
                cmd_parts.append(f'--tmpfs "{path}:{options}"')
            else:
                cmd_parts.append(f'--tmpfs "{path}"')

        # Restore restart policy
        restart_policy = host_config.get("RestartPolicy", {})
        if restart_policy.get("Name"):
            policy = restart_policy["Name"]
            if policy == "on-failure" and restart_policy.get("MaximumRetryCount"):
                policy = f"{policy}:{restart_policy['MaximumRetryCount']}"
            cmd_parts.append(f"--restart {policy}")

        # Restore network mode
        network_mode = host_config.get("NetworkMode", "")
        if network_mode and network_mode not in ("default", "bridge"):
            cmd_parts.append(f"--network {network_mode}")

        # Restore hostname
        hostname = config.get("Hostname", "")
        # Only set if it's a custom hostname (not the container ID)
        if hostname and not hostname.startswith(container_id[:12]):
            cmd_parts.append(f'--hostname "{hostname}"')

        # Restore user
        user = config.get("User", "")
        if user:
            cmd_parts.append(f'--user "{user}"')

        # Restore working directory
        workdir = config.get("WorkingDir", "")
        if workdir:
            cmd_parts.append(f'--workdir "{workdir}"')

        # Restore privileged mode
        if host_config.get("Privileged"):
            cmd_parts.append("--privileged")

        # Restore capabilities
        cap_add = host_config.get("CapAdd", [])
        for cap in cap_add or []:
            cmd_parts.append(f"--cap-add {cap}")

        cap_drop = host_config.get("CapDrop", [])
        for cap in cap_drop or []:
            cmd_parts.append(f"--cap-drop {cap}")

        # Restore devices
        devices = host_config.get("Devices", [])
        for device in devices or []:
            path_on_host = device.get("PathOnHost", "")
            path_in_container = device.get("PathInContainer", "")
            perms = device.get("CgroupPermissions", "rwm")
            if path_on_host:
                device_str = path_on_host
                if path_in_container and path_in_container != path_on_host:
                    device_str += f":{path_in_container}"
                if perms and perms != "rwm":
                    device_str += f":{perms}"
                cmd_parts.append(f'--device "{device_str}"')

        # Restore memory limits
        memory = host_config.get("Memory", 0)
        if memory and memory > 0:
            cmd_parts.append(f"--memory {memory}")

        memory_swap = host_config.get("MemorySwap", 0)
        if memory_swap and memory_swap > 0:
            cmd_parts.append(f"--memory-swap {memory_swap}")

        # Restore CPU limits
        cpu_shares = host_config.get("CpuShares", 0)
        if cpu_shares and cpu_shares > 0:
            cmd_parts.append(f"--cpu-shares {cpu_shares}")

        cpus = host_config.get("NanoCpus", 0)
        if cpus and cpus > 0:
            cmd_parts.append(f"--cpus {cpus / 1e9}")

        # Restore health check (only if custom, not from image)
        healthcheck = config.get("Healthcheck", {})
        if healthcheck and healthcheck.get("Test"):
            test = healthcheck["Test"]
            # Skip if it's just NONE or inherited from image
            if test and test[0] != "NONE":
                if test[0] == "CMD":
                    cmd_str = " ".join(test[1:])
                    cmd_parts.append(f'--health-cmd "{cmd_str}"')
                elif test[0] == "CMD-SHELL":
                    cmd_parts.append(f'--health-cmd "{test[1]}"')

                interval = healthcheck.get("Interval", 0)
                if interval:
                    cmd_parts.append(f"--health-interval {interval // 1000000000}s")

                timeout = healthcheck.get("Timeout", 0)
                if timeout:
                    cmd_parts.append(f"--health-timeout {timeout // 1000000000}s")

                retries = healthcheck.get("Retries", 0)
                if retries:
                    cmd_parts.append(f"--health-retries {retries}")

                start_period = healthcheck.get("StartPeriod", 0)
                if start_period:
                    cmd_parts.append(f"--health-start-period {start_period // 1000000000}s")

        # Add the new image
        cmd_parts.append(new_image)

        # Note: We don't restore Cmd/Entrypoint as these are typically
        # image defaults. Docker will use the new image's defaults automatically.

        # Create new container
        full_cmd = self._cmd(" ".join(cmd_parts))
        stdout, stderr, returncode = await self._connection.async_run_command(full_cmd)

        if returncode != 0:
            _LOGGER.error("Failed to recreate container %s: %s", name, stderr)
            raise ContainerAPIError(f"Failed to recreate container: {stderr}")

        new_container_id = stdout.strip()[:12]

        # Start the container only if it was running before
        if was_running:
            await self.async_start_container(new_container_id)
            _LOGGER.info("Recreated and started container %s with new image %s (new ID: %s)", name, new_image, new_container_id)
        else:
            _LOGGER.info("Recreated container %s with new image %s (new ID: %s, left stopped)", name, new_image, new_container_id)

        return new_container_id

    async def async_pull_image(self, image: str) -> bool:
        """Pull a container image."""
        cmd = self._cmd(f"pull {image}")
        # Use longer timeout for pulling images (5 minutes)
        stdout, stderr, returncode = await self._connection.async_run_command(cmd, timeout=300)

        if returncode != 0:
            _LOGGER.error("Failed to pull image %s: %s", image, stderr)
            raise ContainerAPIError(f"Failed to pull image: {stderr}")

        _LOGGER.info("Pulled image %s", image)
        return True

    async def async_get_image_info(self, image: str) -> ImageInfo | None:
        """Get information about an image."""
        cmd = self._cmd(f"image inspect {image}")
        stdout, stderr, returncode = await self._connection.async_run_command(cmd)

        if returncode != 0:
            return None

        try:
            data = json.loads(stdout)
            if not data:
                return None

            img_data = data[0] if isinstance(data, list) else data
            repo_tags = img_data.get("RepoTags", [])
            repo_tag = repo_tags[0] if repo_tags else image

            # Get image ID and normalize (strip sha256: prefix, keep first 12 hex chars)
            raw_id = img_data.get("Id", "")
            if raw_id.startswith("sha256:"):
                raw_id = raw_id[7:]
            image_id = raw_id[:12]

            return ImageInfo(
                image_id=image_id,
                repository=repo_tag.split(":")[0] if ":" in repo_tag else repo_tag,
                tag=repo_tag.split(":")[-1] if ":" in repo_tag else "latest",
                digest=img_data.get("RepoDigests", [None])[0] if img_data.get("RepoDigests") else None,
                created=img_data.get("Created", ""),
                size=img_data.get("Size", 0),
            )
        except (json.JSONDecodeError, IndexError, KeyError) as err:
            _LOGGER.warning("Failed to parse image info: %s", err)
            return None

    async def async_check_image_update(
        self, image: str, current_image_id: str | None = None
    ) -> tuple[bool, str | None]:
        """Check if a newer version of an image is available.

        Args:
            image: The image name:tag to check
            current_image_id: The container's actual image ID (to compare against)

        Returns:
            Tuple of (update_available, new_digest)
        """
        # Pull latest to get newest version
        cmd = self._cmd(f"pull {image}")
        stdout, stderr, returncode = await self._connection.async_run_command(cmd)

        if returncode != 0:
            _LOGGER.warning("Failed to check for image update: %s", stderr)
            return False, None

        # Get new image info after pull
        new_info = await self.async_get_image_info(image)
        if not new_info:
            return False, None

        # Compare against container's actual image ID if provided
        if current_image_id:
            # Normalize - strip sha256: prefix if present
            current_normalized = current_image_id
            if current_normalized.startswith("sha256:"):
                current_normalized = current_normalized[7:]
            new_normalized = new_info.image_id
            if new_normalized.startswith("sha256:"):
                new_normalized = new_normalized[7:]
            
            _LOGGER.debug(
                "Update check for %s: current=%s new=%s",
                image, current_normalized[:12], new_normalized[:12]
            )
            
            # Compare first 12 chars
            if current_normalized[:12] != new_normalized[:12]:
                return True, new_info.digest or new_info.image_id

        return False, None

    async def async_create_container(
        self,
        name: str,
        image: str,
        ports: dict[str, str] | None = None,
        environment: dict[str, str] | None = None,
        volumes: list[str] | None = None,
        labels: dict[str, str] | None = None,
        restart_policy: str = "unless-stopped",
    ) -> str:
        """Create a new container.

        Returns:
            Container ID
        """
        # Build command parts
        cmd_parts = ["run", "-d", f"--name {name}"]

        # Add managed label
        label_key, label_value = self._label_filter.split("=", 1)
        cmd_parts.append(f'--label "{label_key}={label_value}"')

        # Add custom labels
        if labels:
            for key, value in labels.items():
                cmd_parts.append(f'--label "{key}={value}"')

        # Add restart policy
        cmd_parts.append(f"--restart {restart_policy}")

        # Add ports
        if ports:
            for host_port, container_port in ports.items():
                cmd_parts.append(f"-p {host_port}:{container_port}")

        # Add environment variables
        if environment:
            for key, value in environment.items():
                cmd_parts.append(f'-e "{key}={value}"')

        # Add volumes
        if volumes:
            for volume in volumes:
                cmd_parts.append(f"-v {volume}")

        # Add image
        cmd_parts.append(image)

        cmd = self._cmd(" ".join(cmd_parts))
        stdout, stderr, returncode = await self._connection.async_run_command(cmd)

        if returncode != 0:
            _LOGGER.error("Failed to create container %s: %s", name, stderr)
            raise ContainerAPIError(f"Failed to create container: {stderr}")

        container_id = stdout.strip()[:12]
        _LOGGER.info("Created container %s (%s)", name, container_id)
        return container_id

    async def async_remove_container(
        self, container_id: str, force: bool = False, volumes: bool = False
    ) -> bool:
        """Remove a container."""
        cmd_parts = ["rm"]
        if force:
            cmd_parts.append("-f")
        if volumes:
            cmd_parts.append("-v")
        cmd_parts.append(container_id)

        cmd = self._cmd(" ".join(cmd_parts))
        stdout, stderr, returncode = await self._connection.async_run_command(cmd)

        if returncode != 0:
            _LOGGER.error("Failed to remove container %s: %s", container_id, stderr)
            raise ContainerAPIError(f"Failed to remove container: {stderr}")

        _LOGGER.info("Removed container %s", container_id)
        return True
