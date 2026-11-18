#!/usr/bin/env bash
# Pulls the latest code, syncs dependencies with requirements.lock and restarts all running bots. Run as root
set -euo pipefail

APP_USER=clashwardenbot
APP_DIR=/opt/clashwardenbot/app

cd "$APP_DIR"
sudo -u "$APP_USER" -H git pull --ff-only
sudo -u "$APP_USER" -H uv pip sync requirements.lock
systemctl restart 'clashwardenbot@*'
systemctl --no-pager --lines=0 status 'clashwardenbot@*'
