#!/usr/bin/env bash
# Own installer, based on https://docs.docker.com/engine/install/ubuntu/ .
# Never uninstalls packages, changes WSL defaults, or prunes Docker objects.
set -euo pipefail
. /etc/os-release
if [ "$ID" != ubuntu ] || { [ "$VERSION_ID" != 24.04 ] && [ "$VERSION_ID" != 22.04 ]; }; then
  echo 'Unsupported distribution; use official manual instructions.' >&2
  exit 2
fi
if command -v docker >/dev/null 2>&1; then
  docker info >/dev/null
  docker compose version
  exit 0
fi
for package in docker.io docker-compose docker-compose-v2 containerd runc podman-docker; do
  if dpkg-query -W -f='${Status}' "$package" 2>/dev/null | grep -q 'install ok installed'; then
    echo 'Conflicting existing package; manual review required.' >&2
    exit 3
  fi
done
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq ca-certificates curl
install -m 0755 -d /etc/apt/keyrings
curl --fail --silent --show-error --location https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
printf 'Types: deb\nURIs: https://download.docker.com/linux/ubuntu\nSuites: %s\nComponents: stable\nArchitectures: %s\nSigned-By: /etc/apt/keyrings/docker.asc\n' "$VERSION_CODENAME" "$(dpkg --print-architecture)" > /etc/apt/sources.list.d/docker.sources
apt-get update -qq
apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl start docker
docker info >/dev/null
docker compose version
