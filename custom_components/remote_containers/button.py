"""Button platform for Remote Containers."""

from __future__ import annotations

import logging

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
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
    """Set up Remote Containers buttons."""
    coordinator = entry.runtime_data

    @callback
    def async_add_new_containers() -> None:
        """Add buttons for newly discovered containers."""
        if coordinator.data is None:
            return

        new_entities = []
        for container_name, container in coordinator.data.items():
            if container_name not in coordinator._created_button_ids:
                coordinator._created_button_ids.add(container_name)
                new_entities.append(
                    ContainerRestartButton(coordinator, container_name, entry.entry_id)
                )
                new_entities.append(
                    ContainerRemoveButton(coordinator, container_name, entry.entry_id)
                )

        if new_entities:
            async_add_entities(new_entities)

    async_add_new_containers()

    entry.async_on_unload(
        coordinator.async_add_listener(async_add_new_containers)
    )


class _ContainerButtonBase(
    CoordinatorEntity[RemoteContainersCoordinator], ButtonEntity
):
    """Base class for container buttons."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: RemoteContainersCoordinator,
        container_name: str,
        entry_id: str,
        unique_id_suffix: str,
    ) -> None:
        """Initialize the button."""
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


class ContainerRestartButton(_ContainerButtonBase):
    """Button to restart a container."""

    _attr_translation_key = "restart"
    _attr_device_class = ButtonDeviceClass.RESTART
    _attr_icon = "mdi:restart"

    def __init__(
        self,
        coordinator: RemoteContainersCoordinator,
        container_name: str,
        entry_id: str,
    ) -> None:
        """Initialize the restart button."""
        super().__init__(coordinator, container_name, entry_id, "restart")

    async def async_press(self) -> None:
        """Restart the container."""
        _LOGGER.info("Restarting container %s", self._container_name)
        await self.coordinator.async_restart_container(self._container_name)


class ContainerRemoveButton(_ContainerButtonBase):
    """Button to remove a container."""

    _attr_translation_key = "remove"
    _attr_icon = "mdi:delete"

    def __init__(
        self,
        coordinator: RemoteContainersCoordinator,
        container_name: str,
        entry_id: str,
    ) -> None:
        """Initialize the remove button."""
        super().__init__(coordinator, container_name, entry_id, "remove")

    async def async_press(self) -> None:
        """Stop and remove the container."""
        _LOGGER.info("Removing container %s", self._container_name)
        await self.coordinator.async_remove_container(self._container_name)
