#!/usr/bin/env bash
# Dumps the bot database to /var/backups/clashwardenbot and keeps the last 14 days. Run as root
set -euo pipefail

APP_DIR=/opt/clashwardenbot/app
BACKUP_DIR=/var/backups/clashwardenbot
KEEP_DAYS=14

DATABASE=$(sed -nE 's/^POSTGRES_DATABASE[[:space:]]*=[[:space:]]*//p' "$APP_DIR/.env" | tr -d "\"'\r")
[[ "$DATABASE" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || { echo "Invalid POSTGRES_DATABASE in $APP_DIR/.env"; exit 1; }
mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"
runuser -u postgres -- pg_dump --format=custom "$DATABASE" > "$BACKUP_DIR/$DATABASE-$(date +%F).dump"
find "$BACKUP_DIR" -name '*.dump' -mtime +"$KEEP_DAYS" -delete
