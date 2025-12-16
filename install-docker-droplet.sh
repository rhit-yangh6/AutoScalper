#!/bin/bash
# Install Docker on Linux Droplet (Ubuntu/Debian)
# Run this script on your droplet: bash install-docker-droplet.sh

set -e

echo "================================================"
echo "  Installing Docker on Linux Droplet"
echo "================================================"
echo ""

# Check if running as root or with sudo
if [ "$EUID" -ne 0 ]; then
    echo "Please run with sudo: sudo bash install-docker-droplet.sh"
    exit 1
fi

# Detect OS
if [ -f /etc/os-release ]; then
    . /etc/os-release
    OS=$ID
    echo "Detected OS: $OS"
else
    echo "Cannot detect OS. This script supports Ubuntu/Debian."
    exit 1
fi

echo ""
echo "Step 1: Updating package list..."
apt-get update

echo ""
echo "Step 2: Installing prerequisites..."
apt-get install -y \
    ca-certificates \
    curl \
    gnupg \
    lsb-release

echo ""
echo "Step 3: Adding Docker's official GPG key..."
mkdir -p /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/$OS/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg

echo ""
echo "Step 4: Setting up Docker repository..."
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/$OS \
  $(lsb_release -cs) stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null

echo ""
echo "Step 5: Installing Docker Engine..."
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

echo ""
echo "Step 6: Starting Docker service..."
systemctl enable docker
systemctl start docker

echo ""
echo "Step 7: Adding current user to docker group..."
if [ -n "$SUDO_USER" ]; then
    usermod -aG docker $SUDO_USER
    echo "User $SUDO_USER added to docker group"
else
    echo "Warning: Could not detect user. Run manually: sudo usermod -aG docker YOUR_USERNAME"
fi

echo ""
echo "================================================"
echo "  Docker Installation Complete!"
echo "================================================"
echo ""
echo "Versions installed:"
docker --version
docker compose version

echo ""
echo "IMPORTANT: You need to logout and login again for group changes to take effect."
echo "Or run: newgrp docker"
echo ""
echo "Test Docker with: docker run hello-world"
echo ""
