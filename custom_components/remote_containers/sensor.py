"""Sensor platform for Remote Containers."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import RemoteContainersConfigEntry
from .const import DOMAIN
from .container_api import ContainerInfo
from .coordinator import RemoteContainersCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RemoteContainersConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Remote Containers sensors."""
    coordinator = entry.runtime_data

    @callback
    def async_add_new_containers() -> None:
        """Add sensors for newly discovered containers."""
        if coordinator.data is None:
            return

        new_entities = []
        for container_name, container in coordinator.data.items():
            # Use container name as key to avoid duplicates on container recreation
            if container_name not in coordinator._created_sensor_ids:
                coordinator._created_sensor_ids.add(container_name)
                new_entities.append(
                    ContainerStateSensor(coordinator, container_name, entry.entry_id)
                )

        if new_entities:
            async_add_entities(new_entities)

    # Add entities for current containers
    async_add_new_containers()

    # Listen for new containers on each coordinator update
    entry.async_on_unload(
        coordinator.async_add_listener(async_add_new_containers)
    )


class ContainerStateSensor(CoordinatorEntity[RemoteContainersCoordinator], SensorEntity):
    """Sensor showing container state."""

    _attr_has_entity_name = True
    _attr_name = "State"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:docker"

    def __init__(
        self,
        coordinator: RemoteContainersCoordinator,
        container_name: str,
        entry_id: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._container_name = container_name
        self._entry_id = entry_id
        self._attr_unique_id = f"{entry_id}_{container_name}_state"

    @property
    def container(self) -> ContainerInfo | None:
        """Return the container info."""
        return self.coordinator.get_container(self._container_name)

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return super().available and self.container is not None

    @property
    def native_value(self) -> str | None:
        """Return the container state."""
        container = self.container
        if container is None:
            return None
        # Return the actual status (running, exited, stopped, paused, etc.)
        return container.status

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        container = self.container
        name = container.name if container else self._container_name

        return DeviceInfo(
            identifiers={(DOMAIN, f"{self._entry_id}_{self._container_name}")},
            name=name,
            manufacturer="Docker/Podman",
            model=container.image if container else "Unknown",
            sw_version=container.image_tag if container else None,
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional state attributes."""
        container = self.container
        if container is None:
            return {}

        return {
            "container_id": container.container_id,
            "image": container.image,
            "image_id": container.image_id,
            "created": container.created,
            "ports": container.ports,
            "is_running": container.is_running,
        }

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if self._container_name not in self.coordinator.data:
            self._attr_available = False
        super()._handle_coordinator_update()
