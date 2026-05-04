"""Sensor platform for Remote Containers."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
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
                new_entities.append(
                    ContainerStartedAtSensor(coordinator, container_name, entry.entry_id)
                )

        if new_entities:
            async_add_entities(new_entities)

    # Add entities for current containers
    async_add_new_containers()

    # Listen for new containers on each coordinator update
    entry.async_on_unload(
        coordinator.async_add_listener(async_add_new_containers)
    )


class _ContainerSensorBase(CoordinatorEntity[RemoteContainersCoordinator], SensorEntity):
    """Base class for container sensors."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: RemoteContainersCoordinator,
        container_name: str,
        entry_id: str,
        unique_id_suffix: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._container_name = container_name
        self._entry_id = entry_id
        self._attr_unique_id = f"{entry_id}_{container_name}_{unique_id_suffix}"

    @property
    def container(self) -> ContainerInfo | None:
        """Return the container info."""
        return self.coordinator.get_container(self._container_name)

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return super().available and self.container is not None

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

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if self._container_name not in self.coordinator.data:
            self._attr_available = False
        super()._handle_coordinator_update()


class ContainerStateSensor(_ContainerSensorBase):
    """Sensor showing container state."""

    _attr_translation_key = "state"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:docker"

    def __init__(
        self,
        coordinator: RemoteContainersCoordinator,
        container_name: str,
        entry_id: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, container_name, entry_id, "state")

    @property
    def native_value(self) -> str | None:
        """Return the container state."""
        container = self.container
        if container is None:
            return None
        return container.state

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
            "status": container.status,
            "created": container.created,
            "ports": container.ports,
            "is_running": container.is_running,
        }


class ContainerStartedAtSensor(_ContainerSensorBase):
    """Sensor showing when the container was started."""

    _attr_translation_key = "started_at"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:clock-start"

    def __init__(
        self,
        coordinator: RemoteContainersCoordinator,
        container_name: str,
        entry_id: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, container_name, entry_id, "started_at")

    @property
    def native_value(self) -> datetime | None:
        """Return the container start time as a datetime."""
        container = self.container
        if container is None or not container.started_at:
            return None

        # Docker returns "0001-01-01T00:00:00Z" when never started
        if container.started_at.startswith("0001-"):
            return None

        try:
            return datetime.fromisoformat(container.started_at.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None
