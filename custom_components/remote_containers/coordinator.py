"""DataUpdateCoordinator for Remote Containers."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .connection import SSHConnection, SSHConnectionError
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN
from .container_api import ContainerAPI, ContainerAPIError, ContainerInfo

_LOGGER = logging.getLogger(__name__)


class RemoteContainersCoordinator(DataUpdateCoordinator[dict[str, ContainerInfo]]):
    """Coordinator for fetching container data from remote host."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        connection: SSHConnection,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )
        self.entry = entry
        self.connection = connection
        self.container_api = ContainerAPI(connection, entry.data)
        self._first_refresh = True
        self._known_container_names: set[str] | None = None
        self._created_sensor_ids: set[str] = set()
        self._created_update_ids: set[str] = set()
        self._created_switch_ids: set[str] = set()
        self._created_button_ids: set[str] = set()

    async def _async_update_data(self) -> dict[str, ContainerInfo]:
        """Fetch data from the remote container host."""
        try:
            # Ensure connection is alive
            if not self.connection.is_connected:
                await self.connection.async_connect()

            # Detect runtime on first refresh
            if self._first_refresh:
                await self.container_api.async_detect_runtime()
                self._first_refresh = False

            # Get list of containers
            containers = await self.container_api.async_list_containers()

            # Build result dict keyed by container NAME (stable across recreations)
            result = {c.name: c for c in containers}

            # Track current container names
            current_names = {c.name for c in containers}

            # On first refresh, initialize known containers from device registry
            if self._known_container_names is None:
                self._known_container_names = self._async_get_registered_container_names()
                _LOGGER.debug("Initialized known containers from registry: %s", self._known_container_names)

            # Find removed containers and clean up their entities
            removed_names = self._known_container_names - current_names
            if removed_names:
                await self._async_cleanup_removed_containers(removed_names)

            # Update known containers
            self._known_container_names = current_names

            return result

        except SSHConnectionError as err:
            raise UpdateFailed(f"SSH connection error: {err}") from err
        except ContainerAPIError as err:
            raise UpdateFailed(f"Container API error: {err}") from err
        except Exception as err:
            _LOGGER.exception("Unexpected error fetching container data")
            raise UpdateFailed(f"Unexpected error: {err}") from err

    async def _async_cleanup_removed_containers(self, removed_names: set[str]) -> None:
        """Remove entities and devices for containers that no longer exist."""
        _LOGGER.info("Cleaning up removed containers: %s", removed_names)

        entity_reg = er.async_get(self.hass)
        device_reg = dr.async_get(self.hass)

        for container_name in removed_names:
            # Remove from our tracking sets
            self._created_sensor_ids.discard(container_name)
            self._created_update_ids.discard(container_name)
            self._created_switch_ids.discard(container_name)
            self._created_button_ids.discard(container_name)

            # Find and remove the device (this also removes its entities)
            device_identifier = (DOMAIN, f"{self.entry.entry_id}_{container_name}")
            device = device_reg.async_get_device(identifiers={device_identifier})

            if device:
                _LOGGER.debug("Removing device for container: %s", container_name)
                device_reg.async_remove_device(device.id)

    def _async_get_registered_container_names(self) -> set[str]:
        """Get container names from existing devices in the registry."""
        device_reg = dr.async_get(self.hass)
        names: set[str] = set()

        # Device identifiers are (DOMAIN, "{entry_id}_{container_name}")
        entry_prefix = f"{self.entry.entry_id}_"

        for device in dr.async_entries_for_config_entry(device_reg, self.entry.entry_id):
            for identifier in device.identifiers:
                if identifier[0] == DOMAIN and identifier[1].startswith(entry_prefix):
                    # Extract container name from identifier
                    container_name = identifier[1][len(entry_prefix):]
                    names.add(container_name)

        return names

    def get_container(self, container_name: str) -> ContainerInfo | None:
        """Get a specific container by name."""
        if self.data is None:
            return None
        container = self.data.get(container_name)
        if container is None:
            _LOGGER.debug("Container '%s' not found in data keys: %s", container_name, list(self.data.keys()))
        return container

    async def async_start_container(self, container_name: str) -> None:
        """Start a container and refresh data."""
        await self.container_api.async_start_container(container_name)
        await self.async_request_refresh()

    async def async_stop_container(self, container_name: str) -> None:
        """Stop a container and refresh data."""
        await self.container_api.async_stop_container(container_name)
        await self.async_request_refresh()

    async def async_restart_container(self, container_name: str) -> None:
        """Restart a container and refresh data."""
        await self.container_api.async_restart_container(container_name)
        await self.async_request_refresh()

    async def async_pull_image(self, image: str) -> None:
        """Pull an image."""
        await self.container_api.async_pull_image(image)

    async def async_update_container(self, container_name: str) -> str:
        """Update a container to the latest image version.

        This stops the container, pulls the latest image, and recreates it.

        Returns:
            New container ID
        """
        container = self.get_container(container_name)
        if container is None:
            raise ContainerAPIError(f"Container {container_name} not found")

        # Pull latest image
        await self.container_api.async_pull_image(container.image)

        # Recreate container with new image (use container name, Docker accepts either)
        new_container_id = await self.container_api.async_recreate_container(
            container_name, container.image
        )
        await self.async_request_refresh()
        return new_container_id
