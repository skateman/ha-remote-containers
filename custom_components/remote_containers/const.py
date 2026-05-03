"""Constants for the Remote Containers integration."""

from typing import Final

DOMAIN: Final = "remote_containers"

# Configuration keys
CONF_SSH_HOST: Final = "ssh_host"
CONF_SSH_PORT: Final = "ssh_port"
CONF_SSH_USERNAME: Final = "ssh_username"
CONF_SSH_KEY_FILE: Final = "ssh_key_file"
CONF_CONTAINER_LABEL: Final = "container_label"
CONF_RUNTIME: Final = "runtime"

# Default values
DEFAULT_SSH_PORT: Final = 22
DEFAULT_SSH_USERNAME: Final = "root"
DEFAULT_CONTAINER_LABEL: Final = "ha.remote.managed=true"
DEFAULT_SCAN_INTERVAL: Final = 30  # 30 seconds
DEFAULT_UPDATE_CHECK_INTERVAL: Final = 3600  # 1 hour

# Runtime options
RUNTIME_DOCKER: Final = "docker"
RUNTIME_PODMAN: Final = "podman"
RUNTIME_AUTO: Final = "auto"

# Backup suffix for containers being updated
BACKUP_SUFFIX: Final = "_backup"

# Container states
CONTAINER_STATE_RUNNING: Final = "running"
CONTAINER_STATE_STOPPED: Final = "stopped"
CONTAINER_STATE_PAUSED: Final = "paused"
CONTAINER_STATE_RESTARTING: Final = "restarting"
CONTAINER_STATE_EXITED: Final = "exited"
CONTAINER_STATE_CREATED: Final = "created"

# Services
SERVICE_CREATE: Final = "create"
SERVICE_REMOVE: Final = "remove"
SERVICE_PULL_IMAGE: Final = "pull_image"
SERVICE_CHECK_UPDATES: Final = "check_updates"

# Attributes
ATTR_CONTAINER_ID: Final = "container_id"
ATTR_CONTAINER_NAME: Final = "container_name"
ATTR_IMAGE: Final = "image"
ATTR_IMAGE_ID: Final = "image_id"
ATTR_STATUS: Final = "status"
ATTR_CREATED: Final = "created"
ATTR_PORTS: Final = "ports"
ATTR_LABELS: Final = "labels"

# Platforms
PLATFORMS: Final = ["button", "sensor", "switch", "update"]
