"""Update platform for Remote Containers."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.components.update import (
    UpdateDeviceClass,
    UpdateEntity,
    UpdateEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import RemoteContainersConfigEntry
from .const import DOMAIN, DEFAULT_UPDATE_CHECK_INTERVAL
from .container_api import ContainerInfo
from .coordinator import RemoteContainersCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RemoteContainersConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Remote Containers update entities."""
    coordinator = entry.runtime_data

    @callback
    def async_add_new_containers() -> None:
        """Add update entities for newly discovered containers."""
        if coordinator.data is None:
            return

        new_entities = []
        for container_name, container in coordinator.data.items():
            # Use container name as key to avoid duplicates on container recreation
            if container_name not in coordinator._created_update_ids:
                coordinator._created_update_ids.add(container_name)
                new_entities.append(
                    ContainerUpdate(coordinator, container_name, entry.entry_id)
                )

        if new_entities:
            async_add_entities(new_entities)

    # Add entities for current containers
    async_add_new_containers()

    # Listen for new containers on each coordinator update
    entry.async_on_unload(
        coordinator.async_add_listener(async_add_new_containers)
    )


class ContainerUpdate(CoordinatorEntity[RemoteContainersCoordinator], UpdateEntity):
    """Update entity for container image updates."""

    _attr_has_entity_name = True
    _attr_name = "Update"
    _attr_icon = "mdi:package"
    _attr_device_class = UpdateDeviceClass.FIRMWARE
    _attr_supported_features = (
        UpdateEntityFeature.INSTALL
        | UpdateEntityFeature.PROGRESS
    )

    def __init__(
        self,
        coordinator: RemoteContainersCoordinator,
        container_name: str,
        entry_id: str,
    ) -> None:
        """Initialize the update entity."""
        super().__init__(coordinator)
        self._container_name = container_name
        self._entry_id = entry_id
        self._attr_unique_id = f"{entry_id}_{container_name}_update"
        self._latest_version: str | None = None
        self._update_available = False
        self._in_progress: bool | int = False
        self._checked_for_update = False
        self._unsub_update_check: callable | None = None

    async def async_added_to_hass(self) -> None:
        """Run when entity is added to hass."""
        await super().async_added_to_hass()
        
        # Schedule an update check after entity is added
        self.hass.async_create_task(self._delayed_update_check())
        
        # Set up periodic update checks (every hour by default)
        self._unsub_update_check = async_track_time_interval(
            self.hass,
            self._async_periodic_update_check,
            timedelta(seconds=DEFAULT_UPDATE_CHECK_INTERVAL),
        )

    async def async_will_remove_from_hass(self) -> None:
        """Run when entity is removed from hass."""
        if self._unsub_update_check:
            self._unsub_update_check()
            self._unsub_update_check = None
        await super().async_will_remove_from_hass()

    async def _async_periodic_update_check(self, now=None) -> None:
        """Periodically check for updates."""
        _LOGGER.debug("Periodic update check for %s", self._container_name)
        await self.async_check_for_update()

    async def _delayed_update_check(self) -> None:
        """Check for updates after a short delay."""
        import asyncio
        await asyncio.sleep(10)  # Wait 10 seconds after startup
        if not self._checked_for_update:
            self._checked_for_update = True
            await self.async_check_for_update()

    @property
    def container(self) -> ContainerInfo | None:
        """Return the container info."""
        return self.coordinator.get_container(self._container_name)

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return super().available and self.container is not None

    @property
    def installed_version(self) -> str | None:
        """Return the current image tag with short image ID."""
        if self.container is None:
            return None
        # Include short image ID to detect updates to the same tag
        # Strip sha256: prefix if present
        image_id = self.container.image_id
        if image_id.startswith("sha256:"):
            image_id = image_id[7:]
        return f"{self.container.image_tag} ({image_id[:12]})"

    @property
    def latest_version(self) -> str | None:
        """Return the latest available version."""
        # Don't show updates for stopped containers
        if self.container is not None and not self.container.is_running:
            return self.installed_version
        # If we detected an update, return the new version
        if self._latest_version:
            return self._latest_version
        # Otherwise return current version (no update)
        return self.installed_version

    @property
    def title(self) -> str | None:
        """Return the title of the update."""
        if self.container is None:
            return None
        return f"{self.container.image_name}:{self.container.image_tag}"

    @property
    def in_progress(self) -> bool | int:
        """Return update progress."""
        return self._in_progress

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        container = self.container
        name = container.name if container else self._container_name

        return DeviceInfo(
            identifiers={(DOMAIN, f"{self._entry_id}_{self._container_name}")},
            name=name,
            manufacturer="Docker/Podman",
            model=container.image_name if container else "Unknown",
            sw_version=container.image_tag if container else None,
        )

    @property
    def release_url(self) -> str | None:
        """Return URL to release notes."""
        container = self.container
        if container is None:
            return None

        # Try to construct Docker Hub URL for common images
        image_name = container.image_name
        if "/" not in image_name:
            # Official image
            return f"https://hub.docker.com/_/{image_name}"
        elif image_name.startswith("ghcr.io/"):
            # GitHub Container Registry
            parts = image_name.replace("ghcr.io/", "").split("/")
            if len(parts) >= 2:
                return f"https://github.com/{parts[0]}/{parts[1]}/pkgs/container/{parts[-1]}"
        else:
            # Docker Hub user image
            return f"https://hub.docker.com/r/{image_name}"

        return None

    async def async_install(
        self, version: str | None, backup: bool, **kwargs: Any
    ) -> None:
        """Install the update (pull latest image and recreate container)."""
        container = self.container
        if container is None:
            _LOGGER.error("Cannot update: container not found")
            return

        # Live check: query Docker directly over SSH to verify the container
        # is running right now, not relying on cached coordinator data
        inspect_data = await self.coordinator.container_api._inspect_container(
            container.name
        )
        live_state = inspect_data.get("State", {})
        live_running = (
            live_state.get("Running", False)
            or live_state.get("Status", "").lower() == "running"
        )
        if not live_running:
            raise HomeAssistantError(
                f"Container {container.name} is not running, cannot update"
            )

        _LOGGER.info("Updating container %s to latest image", container.name)
        self._in_progress = True
        self.async_write_ha_state()

        try:
            self._in_progress = 50
            self.async_write_ha_state()

            # Update container (pulls image and recreates)
            new_container_id = await self.coordinator.async_update_container(self._container_name)

            # Clear update state
            self._latest_version = None
            self._update_available = False

            _LOGGER.info("Successfully updated container %s (new ID: %s)", container.name, new_container_id)

        except Exception as err:
            _LOGGER.error("Failed to update container %s: %s", container.name, err)
            raise

        finally:
            self._in_progress = False
            self.async_write_ha_state()

    async def async_check_for_update(self) -> None:
        """Check if a newer image version is available."""
        container = self.container
        if container is None:
            return

        try:
            update_available, new_info = await self.coordinator.container_api.async_check_image_update(
                container.image, container.image_id
            )

            if update_available and new_info:
                self._update_available = True
                # Show new image ID in version string
                # Extract just the hash portion (after last :)
                if "@sha256:" in new_info:
                    new_id = new_info.split("@sha256:")[-1][:12]
                elif new_info.startswith("sha256:"):
                    new_id = new_info[7:19]
                else:
                    new_id = new_info[:12]
                self._latest_version = f"{container.image_tag} ({new_id})"
                _LOGGER.info(
                    "Update available for container %s: %s",
                    container.name,
                    new_info,
                )
            else:
                self._update_available = False
                self._latest_version = None

            self.async_write_ha_state()

        except Exception as err:
            _LOGGER.warning(
                "Failed to check for updates for %s: %s", container.name, err
            )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if self._container_name not in self.coordinator.data:
            self._attr_available = False
        super()._handle_coordinator_update()
