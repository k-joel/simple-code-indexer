#!/usr/bin/env bash
set -euo pipefail

# Run on the Docker HOST (or the WSL2 distro running dockerd), NOT in the container.
# Prerequisites: NVIDIA driver on host (nvidia-smi), Docker installed.

command -v nvidia-smi >/dev/null || { echo "ERROR: nvidia-smi not found; install the NVIDIA host driver first"; exit 1; }
command -v docker     >/dev/null || { echo "ERROR: docker not found; install Docker first"; exit 1; }

# Helper packages
sudo apt-get update
sudo apt-get install -y --no-install-recommends ca-certificates curl gnupg2

# Repository (chained with && so a failed key fetch aborts; --yes makes re-runs idempotent)
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | \
  sudo gpg --dearmor --yes -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg && \
curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list

# Install
sudo apt-get update
sudo apt-get install -y nvidia-container-toolkit

# Configure Docker AND restart so the runtime actually takes effect
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker 2>/dev/null || sudo service docker restart

# Verify
docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi
