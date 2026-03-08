"""The Remote Containers integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import DOMAIN, PLATFORMS
from .coordinator import RemoteContainersCoordinator
from .connection import SSHConnection
from .services import async_setup_services, async_unload_services

_LOGGER = logging.getLogger(__name__)

type RemoteContainersConfigEntry = ConfigEntry[RemoteContainersCoordinator]


async def async_setup_entry(
    hass: HomeAssistant, entry: RemoteContainersConfigEntry
) -> bool:
    """Set up Remote Containers from a config entry."""
    _LOGGER.debug("Setting up Remote Containers integration for %s", entry.title)

    # Create SSH connection
    connection = SSHConnection(hass, entry.data)

    # Test connection
    try:
        await connection.async_connect()
    except Exception as err:
        _LOGGER.error("Failed to connect to remote host: %s", err)
        raise

    # Create coordinator
    coordinator = RemoteContainersCoordinator(hass, entry, connection)

    # Fetch initial data
    await coordinator.async_config_entry_first_refresh()

    # Store coordinator in runtime data
    entry.runtime_data = coordinator

    # Set up platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Set up services
    await async_setup_services(hass)

    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: RemoteContainersConfigEntry
) -> bool:
    """Unload a config entry."""
    _LOGGER.debug("Unloading Remote Containers integration for %s", entry.title)

    # Unload platforms
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        # Close SSH connection
        coordinator: RemoteContainersCoordinator = entry.runtime_data
        await coordinator.connection.async_disconnect()

        # Unload services if no other entries
        remaining_entries = [
            e for e in hass.config_entries.async_entries(DOMAIN) if e.entry_id != entry.entry_id
        ]
        if not remaining_entries:
            await async_unload_services(hass)

    return unload_ok


async def async_reload_entry(
    hass: HomeAssistant, entry: RemoteContainersConfigEntry
) -> None:
    """Reload config entry."""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)
