"""Switch platform for Remote Containers."""

from __future__ import annotations

import logging

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
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
    """Set up Remote Containers switches."""
    coordinator = entry.runtime_data

    @callback
    def async_add_new_containers() -> None:
        """Add switches for newly discovered containers."""
        if coordinator.data is None:
            return

        new_entities = []
        for container_name, container in coordinator.data.items():
            if container_name not in coordinator._created_switch_ids:
                coordinator._created_switch_ids.add(container_name)
                new_entities.append(
                    ContainerRunningSwitch(coordinator, container_name, entry.entry_id)
                )

        if new_entities:
            async_add_entities(new_entities)

    async_add_new_containers()

    entry.async_on_unload(
        coordinator.async_add_listener(async_add_new_containers)
    )


class ContainerRunningSwitch(
    CoordinatorEntity[RemoteContainersCoordinator], SwitchEntity
):
    """Switch to start/stop a container."""

    _attr_has_entity_name = True
    _attr_translation_key = "running"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_icon = "mdi:play-pause"

    def __init__(
        self,
        coordinator: RemoteContainersCoordinator,
        container_name: str,
        entry_id: str,
    ) -> None:
        """Initialize the switch."""
        super().__init__(coordinator)
        self._container_name = container_name
        self._entry_id = entry_id
        self._attr_unique_id = f"{entry_id}_{container_name}_running"

    @property
    def container(self) -> ContainerInfo | None:
        """Return the container info."""
        return self.coordinator.get_container(self._container_name)

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return super().available and self.container is not None

    @property
    def is_on(self) -> bool | None:
        """Return True if the container is running."""
        container = self.container
        if container is None:
            return None
        return container.is_running

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

    async def async_turn_on(self, **kwargs) -> None:
        """Start the container."""
        _LOGGER.info("Starting container %s", self._container_name)
        await self.coordinator.async_start_container(self._container_name)

    async def async_turn_off(self, **kwargs) -> None:
        """Stop the container."""
        _LOGGER.info("Stopping container %s", self._container_name)
        await self.coordinator.async_stop_container(self._container_name)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if self._container_name not in self.coordinator.data:
            self._attr_available = False
        super()._handle_coordinator_update()
