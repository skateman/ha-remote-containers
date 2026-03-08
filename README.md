# Remote Containers for Home Assistant

[![HACS Badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![License](https://img.shields.io/github/license/skateman/ha-remote-containers)](LICENSE)

Manage Docker and Podman containers running on a remote machine directly from Home Assistant. This integration provides lifecycle management (start/stop), image updates, and container operations via SSH.

## Features

- **Monitor container state** via sensor entities
- **Image updates** via update entities with automatic container recreation
- **Docker & Podman** support with auto-detection
- **SSH tunnel** connection (secure, no exposed ports)
- **Label-based discovery** — only manage containers you want
- **Automatic cleanup** — entities removed when containers are deleted
- **Config preservation** — updates preserve env vars, volumes, ports, memory limits, etc.
- **Services** for creating and removing containers

## Installation

### HACS (Recommended)

1. Open HACS in Home Assistant
2. Click the three dots menu → **Custom repositories**
3. Add `https://github.com/skateman/ha-remote-containers` as an **Integration**
4. Search for "Remote Containers" and install it
5. Restart Home Assistant

### Manual Installation

1. Download the latest release
2. Copy `custom_components/remote_containers` to your Home Assistant `config/custom_components/` directory
3. Restart Home Assistant

## Configuration

### Prerequisites

1. **Remote machine**: A server running Docker or Podman
2. **SSH access**: SSH key-based authentication to the remote machine
3. **Container labels**: Label containers you want to manage with `ha.remote.managed=true`

### Label Your Containers

Only containers with the configured label will be discovered. By default, this is `ha.remote.managed=true`.

```bash
# When creating a new container
docker run -d --label "ha.remote.managed=true" --name my-app myimage:latest
```

#### Adding Labels to Existing Containers

Docker doesn't allow adding labels to existing containers — you must recreate them. Use [`runlike`](https://github.com/lavie/runlike) to generate the original `docker run` command, then add the label:

```bash
# Install runlike
pip install runlike

# Get the docker run command for an existing container
runlike my-existing-container

# Output example:
# docker run --name=my-existing-container -p 8080:80 -v /data:/app nginx:latest

# Recreate with the managed label added
docker stop my-existing-container
docker rm my-existing-container
docker run --name=my-existing-container --label "ha.remote.managed=true" -p 8080:80 -v /data:/app nginx:latest
```

Alternatively, use `docker inspect` to manually extract the configuration.

### Add the Integration

1. Go to **Settings** → **Devices & Services**
2. Click **+ Add Integration**
3. Search for **Remote Containers**
4. Enter your SSH connection details:
   - **SSH Host**: IP or hostname of the remote machine
   - **SSH Port**: SSH port (default: 22)
   - **SSH Username**: User with Docker/Podman permissions
   - **SSH Key File**: Path to your private key (e.g., `/config/.ssh/id_rsa`)
   - **Container Label**: Label filter (default: `ha.remote.managed=true`)

The integration auto-detects whether Docker or Podman is available on the remote host.

## Usage

### Entities

Each managed container creates:

| Entity Type | Name | Description |
|-------------|------|-------------|
| Sensor | `sensor.{container}_state` | Shows container state (running, exited, stopped, paused) |
| Update | `update.{container}_update` | Shows available image updates, click Install to update |

### Update Behavior

When you install an update, the integration:

1. Pulls the latest image
2. Stops the container (if running)
3. Removes the old container
4. Creates a new container with the same configuration
5. Starts the container (if it was running before)

**Preserved settings:**
- Labels, environment variables, ports, volumes
- Restart policy, network mode, hostname
- Memory/CPU limits, capabilities, devices
- Health check configuration

### Automatic Cleanup

When a container is deleted or its managed label is removed, the integration automatically removes the corresponding entities and device from Home Assistant at the next polling interval (30 seconds) or on restart.

### Services

#### `remote_containers.create`

Create a new container on the remote host.

```yaml
service: remote_containers.create
data:
  container_name: "my-nginx"
  image: "nginx:latest"
  ports:
    "8080": "80"
  environment:
    NGINX_HOST: "example.com"
  volumes:
    - "/data/nginx:/usr/share/nginx/html"
  restart_policy: "unless-stopped"
```

#### `remote_containers.remove`

Remove a container.

```yaml
service: remote_containers.remove
data:
  container_id: "abc123"
  force: true
  remove_volumes: false
```

#### `remote_containers.pull_image`

Pull an image without creating a container.

```yaml
service: remote_containers.pull_image
data:
  image: "nginx:latest"
```

#### `remote_containers.check_updates`

Manually trigger an update check for all managed containers.

```yaml
service: remote_containers.check_updates
```

## Troubleshooting

### SSH Connection Issues

1. Verify you can SSH manually: `ssh -i /path/to/key user@host`
2. Ensure the key has correct permissions: `chmod 600 /path/to/key`
3. Check the Home Assistant logs for detailed error messages

### Containers Not Appearing

1. Verify containers have the correct label: `docker ps -a --filter "label=ha.remote.managed=true"`
2. Reload the integration after adding labels
3. Check that the SSH user has permission to run Docker/Podman commands

### Permission Denied

The SSH user must be able to run Docker/Podman without sudo:

```bash
# For Docker
sudo usermod -aG docker $USER

# For Podman (usually works without additional setup)
```

## Contributing

Contributions are welcome! Please open an issue or pull request.

## License

MIT License - see [LICENSE](LICENSE) for details.
