"""Config flow for Remote Containers integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.core import HomeAssistant

from .const import (
    CONF_CONTAINER_LABEL,
    CONF_SSH_HOST,
    CONF_SSH_KEY_FILE,
    CONF_SSH_PORT,
    CONF_SSH_USERNAME,
    DEFAULT_CONTAINER_LABEL,
    DEFAULT_SSH_PORT,
    DEFAULT_SSH_USERNAME,
    DOMAIN,
)
from .connection import async_test_ssh_connection

_LOGGER = logging.getLogger(__name__)


def _get_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    """Return the config flow schema with optional defaults."""
    defaults = defaults or {}
    return vol.Schema(
        {
            vol.Required(
                CONF_SSH_HOST, default=defaults.get(CONF_SSH_HOST, "")
            ): str,
            vol.Required(
                CONF_SSH_PORT, default=defaults.get(CONF_SSH_PORT, DEFAULT_SSH_PORT)
            ): int,
            vol.Required(
                CONF_SSH_USERNAME,
                default=defaults.get(CONF_SSH_USERNAME, DEFAULT_SSH_USERNAME),
            ): str,
            vol.Optional(
                CONF_SSH_KEY_FILE, default=defaults.get(CONF_SSH_KEY_FILE, "")
            ): str,
            vol.Required(
                CONF_CONTAINER_LABEL,
                default=defaults.get(CONF_CONTAINER_LABEL, DEFAULT_CONTAINER_LABEL),
            ): str,
        }
    )


class RemoteContainersConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Remote Containers."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Set unique ID based on host
            await self.async_set_unique_id(user_input[CONF_SSH_HOST])
            self._abort_if_unique_id_configured()

            # Test SSH connection
            ssh_key = user_input.get(CONF_SSH_KEY_FILE) or None
            success, error_msg = await async_test_ssh_connection(
                host=user_input[CONF_SSH_HOST],
                port=user_input[CONF_SSH_PORT],
                username=user_input[CONF_SSH_USERNAME],
                key_file=ssh_key,
            )

            if success:
                # Clean up empty optional fields
                data = {k: v for k, v in user_input.items() if v}
                return self.async_create_entry(
                    title=user_input[CONF_SSH_HOST],
                    data=data,
                )

            _LOGGER.error("SSH connection test failed: %s", error_msg)
            errors["base"] = "cannot_connect"
            if "authentication" in error_msg.lower():
                errors["base"] = "invalid_auth"
            elif "key file" in error_msg.lower():
                errors[CONF_SSH_KEY_FILE] = "invalid_key_file"

        return self.async_show_form(
            step_id="user",
            data_schema=_get_schema(user_input),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle reconfiguration."""
        errors: dict[str, str] = {}
        reconfigure_entry = self._get_reconfigure_entry()

        if user_input is not None:
            # Test SSH connection
            ssh_key = user_input.get(CONF_SSH_KEY_FILE) or None
            success, error_msg = await async_test_ssh_connection(
                host=user_input[CONF_SSH_HOST],
                port=user_input[CONF_SSH_PORT],
                username=user_input[CONF_SSH_USERNAME],
                key_file=ssh_key,
            )

            if success:
                # Clean up empty optional fields
                data = {k: v for k, v in user_input.items() if v}
                return self.async_update_reload_and_abort(
                    reconfigure_entry,
                    data=data,
                )

            _LOGGER.error("SSH connection test failed: %s", error_msg)
            errors["base"] = "cannot_connect"
            if "authentication" in error_msg.lower():
                errors["base"] = "invalid_auth"
            elif "key file" in error_msg.lower():
                errors[CONF_SSH_KEY_FILE] = "invalid_key_file"

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_get_schema(reconfigure_entry.data),
            errors=errors,
        )
