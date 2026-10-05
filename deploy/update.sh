#!/bin/bash
# Pull the latest code from GitHub and rebuild/restart the bot. Run on the EC2 host.
set -euo pipefail
cd "$(dirname "$0")/.."

git pull --ff-only
docker compose up -d --build
docker image prune -f
docker compose ps
