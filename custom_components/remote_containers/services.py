"""Service handlers for Remote Containers."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv

from .const import (
    ATTR_CONTAINER_ID,
    ATTR_CONTAINER_NAME,
    ATTR_IMAGE,
    DOMAIN,
    SERVICE_CHECK_UPDATES,
    SERVICE_CREATE,
    SERVICE_PULL_IMAGE,
    SERVICE_REMOVE,
)

_LOGGER = logging.getLogger(__name__)

SERVICE_CREATE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_CONTAINER_NAME): cv.string,
        vol.Required(ATTR_IMAGE): cv.string,
        vol.Optional("ports"): vol.Schema({cv.string: cv.string}),
        vol.Optional("environment"): vol.Schema({cv.string: cv.string}),
        vol.Optional("volumes"): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional("labels"): vol.Schema({cv.string: cv.string}),
        vol.Optional("restart_policy", default="unless-stopped"): cv.string,
    }
)

SERVICE_REMOVE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_CONTAINER_ID): cv.string,
        vol.Optional("force", default=False): cv.boolean,
        vol.Optional("remove_volumes", default=False): cv.boolean,
    }
)

SERVICE_PULL_IMAGE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_IMAGE): cv.string,
    }
)


def _get_first_coordinator(hass: HomeAssistant):
    """Get the first available coordinator."""
    from . import RemoteContainersConfigEntry

    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        raise ValueError("No Remote Containers integration configured")

    entry: RemoteContainersConfigEntry = entries[0]
    return entry.runtime_data


async def async_handle_create_container(call: ServiceCall) -> None:
    """Handle the create container service."""
    hass = call.hass
    coordinator = _get_first_coordinator(hass)

    name = call.data[ATTR_CONTAINER_NAME]
    image = call.data[ATTR_IMAGE]
    ports = call.data.get("ports")
    environment = call.data.get("environment")
    volumes = call.data.get("volumes")
    labels = call.data.get("labels")
    restart_policy = call.data.get("restart_policy", "unless-stopped")

    _LOGGER.info("Creating container %s from image %s", name, image)

    container_id = await coordinator.container_api.async_create_container(
        name=name,
        image=image,
        ports=ports,
        environment=environment,
        volumes=volumes,
        labels=labels,
        restart_policy=restart_policy,
    )

    # Refresh coordinator to pick up new container
    await coordinator.async_request_refresh()

    _LOGGER.info("Created container %s with ID %s", name, container_id)


async def async_handle_remove_container(call: ServiceCall) -> None:
    """Handle the remove container service."""
    hass = call.hass
    coordinator = _get_first_coordinator(hass)

    container_id = call.data[ATTR_CONTAINER_ID]
    force = call.data.get("force", False)
    remove_volumes = call.data.get("remove_volumes", False)

    _LOGGER.info("Removing container %s", container_id)

    await coordinator.container_api.async_remove_container(
        container_id=container_id,
        force=force,
        volumes=remove_volumes,
    )

    # Refresh coordinator to remove container from state
    await coordinator.async_request_refresh()


async def async_handle_pull_image(call: ServiceCall) -> None:
    """Handle the pull image service."""
    hass = call.hass
    coordinator = _get_first_coordinator(hass)

    image = call.data[ATTR_IMAGE]

    _LOGGER.info("Pulling image %s", image)

    await coordinator.async_pull_image(image)


async def async_handle_check_updates(call: ServiceCall) -> None:
    """Handle the check updates service."""
    hass = call.hass
    
    # Find all update entities and trigger update check
    from homeassistant.helpers import entity_registry as er
    
    registry = er.async_get(hass)
    update_entities = [
        entry for entry in registry.entities.values()
        if entry.platform == DOMAIN and entry.domain == "update"
    ]
    
    _LOGGER.info("Checking for updates on %d containers", len(update_entities))
    
    for entity_entry in update_entities:
        # Get the entity and call its update check method
        entity = hass.data.get("entity_components", {}).get("update", {}).get_entity(entity_entry.entity_id)
        if entity and hasattr(entity, "async_check_for_update"):
            await entity.async_check_for_update()


async def async_setup_services(hass: HomeAssistant) -> None:
    """Set up services for Remote Containers."""
    if hass.services.has_service(DOMAIN, SERVICE_CREATE):
        return  # Services already registered

    hass.services.async_register(
        DOMAIN,
        SERVICE_CREATE,
        async_handle_create_container,
        schema=SERVICE_CREATE_SCHEMA,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_REMOVE,
        async_handle_remove_container,
        schema=SERVICE_REMOVE_SCHEMA,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_PULL_IMAGE,
        async_handle_pull_image,
        schema=SERVICE_PULL_IMAGE_SCHEMA,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_CHECK_UPDATES,
        async_handle_check_updates,
    )

    _LOGGER.debug("Registered Remote Containers services")


async def async_unload_services(hass: HomeAssistant) -> None:
    """Unload services for Remote Containers."""
    hass.services.async_remove(DOMAIN, SERVICE_CREATE)
    hass.services.async_remove(DOMAIN, SERVICE_REMOVE)
    hass.services.async_remove(DOMAIN, SERVICE_PULL_IMAGE)
    hass.services.async_remove(DOMAIN, SERVICE_CHECK_UPDATES)

    _LOGGER.debug("Unloaded Remote Containers services")
