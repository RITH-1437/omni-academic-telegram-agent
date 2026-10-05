#!/bin/bash
# EC2 user-data: prepares an Ubuntu 24.04 host to run the bot with Docker Compose.
# The bot is started separately once .env has been copied to $APP_DIR (see README "Deploy to AWS EC2").
set -euxo pipefail

REPO_URL="https://github.com/RITH-1437/omni-academic-telegram-agent.git"
APP_DIR="/opt/telegram-bot"
APP_USER="ubuntu"

# 2 GB swap: t3.micro has 1 GB RAM; image builds and large PDF parsing can spike memory
if [ ! -f /swapfile ]; then
  fallocate -l 2G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

# Docker Engine + Compose plugin; enabled at boot so the bot comes back after reboots
if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | sh
fi
systemctl enable --now docker
usermod -aG docker "$APP_USER"

apt-get install -y git unattended-upgrades

if [ ! -d "$APP_DIR/.git" ]; then
  git clone "$REPO_URL" "$APP_DIR"
fi
chown -R "$APP_USER:$APP_USER" "$APP_DIR"

# data/ is bind-mounted into the container, which runs as uid 1000 (appuser);
# if Docker created it, it would be root-owned and SQLite could not write to it
mkdir -p "$APP_DIR/data"
chown 1000:1000 "$APP_DIR/data"

touch /var/lib/cloud/instance/bot-bootstrap-done
