"""Tests for retryable Remote Containers setup failures."""

from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.exceptions import ConfigEntryNotReady

from custom_components.remote_containers import async_setup_entry
from custom_components.remote_containers.connection import SSHConnectionError


class SetupEntryTests(IsolatedAsyncioTestCase):
    """Test recovery when the remote host is unavailable at startup."""

    def setUp(self) -> None:
        self.hass = SimpleNamespace(
            config_entries=SimpleNamespace(async_forward_entry_setups=AsyncMock())
        )
        self.entry = SimpleNamespace(
            entry_id="test-entry", title="Remote host", data={}, runtime_data=None
        )
        self.connection = MagicMock(async_connect=AsyncMock())
        self.coordinator = MagicMock(async_config_entry_first_refresh=AsyncMock())
        self.enterContext(
            patch(
                "custom_components.remote_containers.SSHConnection",
                return_value=self.connection,
            )
        )
        self.coordinator_factory = self.enterContext(
            patch(
                "custom_components.remote_containers.RemoteContainersCoordinator",
                return_value=self.coordinator,
            )
        )
        self.setup_services = self.enterContext(
            patch(
                "custom_components.remote_containers.async_setup_services",
                new_callable=AsyncMock,
            )
        )

    async def test_connection_failures_are_retryable(self) -> None:
        for message in ("Network unreachable", "Connection timed out"):
            with self.subTest(message=message):
                error = SSHConnectionError(message)
                self.connection.async_connect.side_effect = error

                with self.assertRaises(ConfigEntryNotReady) as raised:
                    await async_setup_entry(self.hass, self.entry)

                self.assertEqual(str(raised.exception), message)
                self.assertIs(raised.exception.__cause__, error)

        self.coordinator_factory.assert_not_called()
        self.hass.config_entries.async_forward_entry_setups.assert_not_awaited()
        self.setup_services.assert_not_awaited()

    async def test_setup_succeeds_after_connection_recovers(self) -> None:
        self.connection.async_connect.side_effect = [
            SSHConnectionError("Network unreachable"),
            None,
        ]

        with self.assertRaises(ConfigEntryNotReady):
            await async_setup_entry(self.hass, self.entry)

        self.assertTrue(await async_setup_entry(self.hass, self.entry))
        self.assertIs(self.entry.runtime_data, self.coordinator)
        self.coordinator.async_config_entry_first_refresh.assert_awaited_once()
        self.hass.config_entries.async_forward_entry_setups.assert_awaited_once()
        self.setup_services.assert_awaited_once_with(self.hass)

    async def test_unexpected_errors_are_not_converted_to_retries(self) -> None:
        self.connection.async_connect.side_effect = ValueError("Invalid configuration")

        with self.assertRaisesRegex(ValueError, "Invalid configuration"):
            await async_setup_entry(self.hass, self.entry)

        self.coordinator_factory.assert_not_called()
