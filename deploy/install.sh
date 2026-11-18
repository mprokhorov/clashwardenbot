#!/usr/bin/env bash
# Sets up the production machine: bots, deployer and control panel bot. Run as root.
# Everything that runs as root is copied to root-owned /opt/clashwardenbot-control, never run from the bot checkout.
# Safe to run again: it only adds what is missing and refreshes the control panel code and systemd units.
#
# Usage: install.sh [--branch dev] [--env /root/clashwardenbot/.env] [--old-dir /root/clashwardenbot] [--ad-dir /root/clashwardenbot]
#   --branch   branch for the first clone (later the branch is chosen in the control panel)
#   --env      existing .env to copy if the new installation has none
#   --old-dir  previous installation to compare with the repository before the bots are switched over
#   --ad-dir   directory with ad.py, ad/ and ad.session to move to /opt/clashwardenbot-ad (once)
set -euo pipefail

REPO_URL=https://github.com/mprokhorov/clashwardenbot
APP_USER=clashwardenbot
CONTROL_USER=clashwardenbot-control
APP_HOME=/opt/clashwardenbot
APP_DIR=$APP_HOME/app
CONTROL_DIR=/opt/clashwardenbot-control
CONTROL_STATE_DIR=/var/lib/clashwardenbot-control
DEPLOY_STATUS_DIR=/var/lib/clashwardenbot-deploy
CONTROL_ENV=/etc/clashwardenbot/control.env
AD_USER=clashwardenbot-ad
AD_DIR=/opt/clashwardenbot-ad
UNITS_DIR=/etc/systemd/system

BRANCH=dev
OLD_ENV=
OLD_DIR=
OLD_AD_DIR=
while [ $# -gt 0 ]; do
    case "$1" in
        --branch) BRANCH=$2; shift 2 ;;
        --env) OLD_ENV=$2; shift 2 ;;
        --old-dir) OLD_DIR=$2; shift 2 ;;
        --ad-dir) OLD_AD_DIR=$2; shift 2 ;;
        *) echo "Unknown argument: $1"; exit 1 ;;
    esac
done

step() { echo; echo "==> $*"; }

[ "$(id -u)" -eq 0 ] || { echo "Run as root"; exit 1; }
cd /

step "uv"
if ! command -v uv >/dev/null; then
    curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin INSTALLER_NO_MODIFY_PATH=1 sh
fi
uv --version

step "Users"
id -u "$APP_USER" >/dev/null 2>&1 || useradd --system --create-home --home-dir "$APP_HOME" --shell /usr/sbin/nologin "$APP_USER"
id -u "$CONTROL_USER" >/dev/null 2>&1 || useradd --system --no-create-home --home-dir "$CONTROL_STATE_DIR" --shell /usr/sbin/nologin "$CONTROL_USER"
chmod 755 "$APP_HOME"

step "Bot code and dependencies ($APP_DIR)"
if [ ! -d "$APP_DIR/.git" ]; then
    runuser -u "$APP_USER" -- git clone --quiet --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
fi
cd "$APP_DIR"
[ -d .venv ] || runuser -u "$APP_USER" -- uv venv --quiet --python 3.12 .venv
runuser -u "$APP_USER" -- uv pip sync --quiet --python .venv/bin/python requirements.lock
if [ ! -f .env ]; then
    [ -n "$OLD_ENV" ] || { echo "No $APP_DIR/.env: pass --env /path/to/.env"; exit 1; }
    install -o "$APP_USER" -g "$APP_USER" -m 600 "$OLD_ENV" .env
fi
cd /
echo "$(runuser -u "$APP_USER" -- git -C "$APP_DIR" log -1 --format='%D: %h %s')"

step "Control panel code ($CONTROL_DIR)"
install -d -o root -g root -m 755 "$CONTROL_DIR"
install -o root -g root -m 644 "$APP_DIR/control/deployer.py" "$APP_DIR/control/control_bot.py" "$APP_DIR/control/requirements.lock" "$CONTROL_DIR/"
install -o root -g root -m 755 "$APP_DIR/deploy/backup.sh" "$CONTROL_DIR/"
[ -d "$CONTROL_DIR/.venv" ] || UV_PYTHON_INSTALL_DIR="$CONTROL_DIR/python" uv venv --quiet --python 3.12 "$CONTROL_DIR/.venv"
UV_PYTHON_INSTALL_DIR="$CONTROL_DIR/python" uv pip sync --quiet --python "$CONTROL_DIR/.venv/bin/python" "$CONTROL_DIR/requirements.lock"

IS_AD_MIGRATED=false
if [ -f "$AD_DIR/ad.py" ] || [ -n "$OLD_AD_DIR" ]; then
    step "Ad script ($AD_DIR)"
    id -u "$AD_USER" >/dev/null 2>&1 || useradd --system --create-home --home-dir "$AD_DIR" --shell /usr/sbin/nologin "$AD_USER"
    chmod 700 "$AD_DIR"
    if [ ! -f "$AD_DIR/ad.py" ]; then
        [ -f "$OLD_AD_DIR/ad.py" ] || { echo "No $OLD_AD_DIR/ad.py"; exit 1; }
        # One Telegram session must never run in two processes, so the old ad script is stopped before copying
        systemctl stop clashwardenbot-ad.service 2>/dev/null || true
        cp -a "$OLD_AD_DIR/ad.py" "$OLD_AD_DIR/ad" "$AD_DIR/"
        cp -a "$OLD_AD_DIR"/ad.session* "$OLD_AD_DIR"/ad.log* "$AD_DIR/" 2>/dev/null || true
        chown -R "$AD_USER":"$AD_USER" "$AD_DIR"
        IS_AD_MIGRATED=true
    fi
    install -o "$AD_USER" -g "$AD_USER" -m 644 "$APP_DIR/deploy/ad/requirements.lock" "$AD_DIR/requirements.lock"
    cd "$AD_DIR"
    [ -d .venv ] || runuser -u "$AD_USER" -- uv venv --quiet --python 3.12 .venv
    runuser -u "$AD_USER" -- uv pip sync --quiet --python .venv/bin/python requirements.lock
    cd /
    ls -la "$AD_DIR"
fi

step "Control panel settings ($CONTROL_ENV)"
install -d -o root -g root -m 755 /etc/clashwardenbot
if [ ! -f "$CONTROL_ENV" ]; then
    DEFAULT_OWNER_ID=$(sed -nE 's/^TELEGRAM_BOT_OWNER_ID[[:space:]]*=[[:space:]]*//p' "$APP_DIR/.env" | tr -d "\"'\r")
    read -rp "Telegram ID владельца пульта [$DEFAULT_OWNER_ID]: " OWNER_ID
    OWNER_ID=${OWNER_ID:-$DEFAULT_OWNER_ID}
    read -rsp "Токен бота-пульта (от @BotFather, ввод скрыт): " CONTROL_TOKEN
    echo
    umask 027
    printf 'CONTROL_BOT_TOKEN=%s\nCONTROL_BOT_OWNER_ID=%s\n' "$CONTROL_TOKEN" "$OWNER_ID" > "$CONTROL_ENV"
    umask 022
    chown root:"$CONTROL_USER" "$CONTROL_ENV"
    chmod 640 "$CONTROL_ENV"
fi

step "State and status directories"
install -d -o "$CONTROL_USER" -g "$CONTROL_USER" -m 755 "$CONTROL_STATE_DIR"
install -d -o root -g root -m 755 "$DEPLOY_STATUS_DIR"
if [ ! -f "$CONTROL_STATE_DIR/state.json" ]; then
    # The initial state repeats what is running now, so nothing changes until it is edited in the panel
    INSTANCES=$(systemctl list-units --all --plain --no-legend 'clashwardenbot@*.service' | awk '{print $1}' \
        | while read -r unit; do [ "$(systemctl is-enabled "$unit" 2>/dev/null)" = enabled ] && echo "$unit"; done \
        | sed -E 's/clashwardenbot@([0-9]+)\.service/\1/' | paste -sd, -)
    AD_ENABLED=false
    [ "$(systemctl is-enabled clashwardenbot-ad.service 2>/dev/null)" = enabled ] && AD_ENABLED=true
    CURRENT_BRANCH=$(runuser -u "$APP_USER" -- git -C "$APP_DIR" rev-parse --abbrev-ref HEAD)
    printf '{"branch": "%s", "instances": [%s], "ad_enabled": %s, "auto_update": true}\n' \
        "$CURRENT_BRANCH" "$INSTANCES" "$AD_ENABLED" > "$CONTROL_STATE_DIR/state.json"
    chown "$CONTROL_USER":"$CONTROL_USER" "$CONTROL_STATE_DIR/state.json"
fi
cat "$CONTROL_STATE_DIR/state.json"

IS_FIRST_MIGRATION=false
if [ -f "$UNITS_DIR/clashwardenbot@.service" ] && ! grep -q "WorkingDirectory=$APP_DIR" "$UNITS_DIR/clashwardenbot@.service"; then
    IS_FIRST_MIGRATION=true
fi
if $IS_FIRST_MIGRATION && [ -n "$OLD_DIR" ]; then
    step "Differences between $OLD_DIR and the repository"
    diff -rq -x venv -x .venv -x __pycache__ -x '*.log' -x '*.session' -x '*.session-journal' -x .env \
        -x .git -x .gitignore -x deploy -x control -x systemd -x requirements.lock "$OLD_DIR" "$APP_DIR" || true
    read -rp "Переключить ботов на $APP_DIR? [y/N] " ANSWER
    [ "$ANSWER" = y ] || [ "$ANSWER" = Y ] || { echo "Остановлено, боты работают по-старому"; exit 0; }
fi

step "systemd units"
BACKUP_DIR="$UNITS_DIR/clashwardenbot-units-backup-$(date +%F-%H%M%S)"
mkdir -p "$BACKUP_DIR"
cp -a "$UNITS_DIR"/clashwardenbot*.service "$UNITS_DIR"/clashwardenbot*.timer "$UNITS_DIR"/clashwardenbot*.path "$BACKUP_DIR"/ 2>/dev/null || true
echo "Previous units saved to $BACKUP_DIR"
cp "$APP_DIR"/deploy/*.service "$APP_DIR"/deploy/*.timer "$APP_DIR"/deploy/*.path "$UNITS_DIR"/
[ -f "$AD_DIR/ad.py" ] && cp "$APP_DIR/deploy/ad/clashwardenbot-ad.service" "$UNITS_DIR"/
cp "$APP_DIR/deploy/journald@clashwardenbot.conf" /etc/systemd/
systemctl daemon-reload
systemctl try-restart systemd-journald@clashwardenbot.service

step "Restarting bots on the new installation"
for number in $(python3 -c 'import json, sys; print(*json.load(open(sys.argv[1])).get("instances", []))' "$CONTROL_STATE_DIR/state.json"); do
    systemctl restart "clashwardenbot@$number.service"
    echo "clashwardenbot@$number: $(systemctl is-active "clashwardenbot@$number.service")"
done

if $IS_AD_MIGRATED && [ "$(systemctl is-enabled clashwardenbot-ad.service 2>/dev/null)" = enabled ]; then
    systemctl restart clashwardenbot-ad.service
    sleep 5
    echo "clashwardenbot-ad: $(systemctl is-active clashwardenbot-ad.service)"
fi

step "Deployer, control panel, daily restart and backups"
systemctl enable --now clashwardenbot-deploy.timer clashwardenbot-deploy.path clashwardenbot-control.service \
    clashwardenbot-restart.timer clashwardenbot-backup.timer
systemctl restart clashwardenbot-control.service
systemctl --no-pager --lines=0 status 'clashwardenbot@*' clashwardenbot-control.service || true

echo
echo "Готово. Напиши боту-пульту /panel"
