"""SSH connection manager for Remote Containers."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import asyncssh

from homeassistant.core import HomeAssistant

from .const import (
    CONF_SSH_HOST,
    CONF_SSH_KEY_FILE,
    CONF_SSH_PORT,
    CONF_SSH_USERNAME,
    DEFAULT_SSH_PORT,
    DEFAULT_SSH_USERNAME,
)

_LOGGER = logging.getLogger(__name__)

# Connection timeout in seconds
SSH_CONNECT_TIMEOUT = 30
SSH_COMMAND_TIMEOUT = 60


class SSHConnectionError(Exception):
    """Exception raised when SSH connection fails."""


class SSHConnection:
    """Manages SSH connection to remote container host."""

    def __init__(self, hass: HomeAssistant, config: dict[str, Any]) -> None:
        """Initialize the SSH connection."""
        self.hass = hass
        self._host = config[CONF_SSH_HOST]
        self._port = config.get(CONF_SSH_PORT, DEFAULT_SSH_PORT)
        self._username = config.get(CONF_SSH_USERNAME, DEFAULT_SSH_USERNAME)
        self._key_file = config.get(CONF_SSH_KEY_FILE)
        self._connection: asyncssh.SSHClientConnection | None = None
        self._lock = asyncio.Lock()

    @property
    def is_connected(self) -> bool:
        """Return True if connected."""
        return self._connection is not None and not self._connection.is_closed()

    async def async_connect(self) -> None:
        """Establish SSH connection."""
        async with self._lock:
            if self.is_connected:
                return

            _LOGGER.debug(
                "Connecting to %s@%s:%s", self._username, self._host, self._port
            )

            try:
                connect_kwargs: dict[str, Any] = {
                    "host": self._host,
                    "port": self._port,
                    "username": self._username,
                    "known_hosts": None,  # Disable host key checking (configurable later)
                    "login_timeout": SSH_CONNECT_TIMEOUT,
                }

                if self._key_file:
                    connect_kwargs["client_keys"] = [self._key_file]

                async with asyncio.timeout(SSH_CONNECT_TIMEOUT):
                    self._connection = await asyncssh.connect(**connect_kwargs)
                _LOGGER.info("SSH connection established to %s", self._host)

            except asyncio.TimeoutError:
                _LOGGER.error("SSH connection timed out to %s", self._host)
                raise SSHConnectionError(f"Connection timed out to {self._host}") from None
            except asyncssh.Error as err:
                _LOGGER.error("SSH connection failed: %s", err)
                raise SSHConnectionError(f"Failed to connect to {self._host}: {err}") from err
            except OSError as err:
                _LOGGER.error("Network error connecting to %s: %s", self._host, err)
                raise SSHConnectionError(f"Network error: {err}") from err

    async def async_disconnect(self) -> None:
        """Close the SSH connection."""
        async with self._lock:
            if self._connection is not None:
                self._connection.close()
                await self._connection.wait_closed()
                self._connection = None
                _LOGGER.info("SSH connection closed")

    async def async_run_command(self, command: str, timeout: int | None = None) -> tuple[str, str, int]:
        """Run a command over SSH.

        Args:
            command: The command to run
            timeout: Optional timeout in seconds (default: SSH_COMMAND_TIMEOUT)

        Returns:
            Tuple of (stdout, stderr, return_code)
        """
        if not self.is_connected:
            await self.async_connect()

        cmd_timeout = timeout if timeout is not None else SSH_COMMAND_TIMEOUT
        try:
            async with asyncio.timeout(cmd_timeout):
                result = await self._connection.run(command, check=False)
            return (
                result.stdout or "",
                result.stderr or "",
                result.returncode or 0,
            )
        except asyncio.TimeoutError:
            _LOGGER.error("Command execution timed out: %s", command[:50])
            await self.async_disconnect()
            raise SSHConnectionError(f"Command timed out") from None
        except asyncssh.Error as err:
            _LOGGER.error("Command execution failed: %s", err)
            # Try to reconnect on error
            await self.async_disconnect()
            raise SSHConnectionError(f"Command failed: {err}") from err

    async def async_test_connection(self) -> bool:
        """Test if SSH connection is working."""
        try:
            await self.async_connect()
            stdout, stderr, returncode = await self.async_run_command("echo 'test'")
            return returncode == 0 and "test" in stdout
        except SSHConnectionError:
            return False


async def async_test_ssh_connection(
    host: str,
    port: int,
    username: str,
    key_file: str | None = None,
) -> tuple[bool, str]:
    """Test SSH connection with provided credentials.

    Returns:
        Tuple of (success, error_message)
    """
    try:
        connect_kwargs: dict[str, Any] = {
            "host": host,
            "port": port,
            "username": username,
            "known_hosts": None,
        }

        if key_file:
            connect_kwargs["client_keys"] = [key_file]

        async with asyncssh.connect(**connect_kwargs) as conn:
            result = await conn.run("echo 'test'", check=True)
            if result.returncode == 0:
                return True, ""
            return False, "Connection test command failed"

    except asyncssh.PermissionDenied as err:
        return False, f"Authentication failed: {err}"
    except asyncssh.HostKeyNotVerifiable as err:
        return False, f"Host key verification failed: {err}"
    except asyncssh.Error as err:
        return False, f"SSH error: {err}"
    except OSError as err:
        return False, f"Connection error: {err}"
    except FileNotFoundError:
        return False, "SSH key file not found"
