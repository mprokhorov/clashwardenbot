# clashwardenbot

## Demonstration

Link to an example: [t.me/clashwardenbot](https://t.me/clashwardenbot)

## Requirements

- Python 3.12
- PostgreSQL 16.2

## Installation

### Clone repository

```bash
$ git clone https://github.com/mprokhorov/clashwardenbot
$ cd clashwardenbot
```

### Setup virtual environment and install dependencies

```bash
$ uv venv --python 3.12
$ uv pip sync requirements.lock
```

`requirements.txt` holds the direct dependencies with version bounds, `requirements.lock` pins exact versions of everything. After changing `requirements.txt`, regenerate the lock:

```bash
$ uv pip compile requirements.txt --python-version 3.12 --python-platform x86_64-manylinux_2_31 -o requirements.lock
```
### Create PostgreSQL database

Use ```schema.sql``` to create schema and ```insert_group_members.py``` to insert group members to database _(Telegram client required)_


### Create and configure `.env` file

```
TELEGRAM_API_CLIENT_NAME = name
TELEGRAM_API_ID = 1234567890
TELEGRAM_API_HASH = 1234567890abcdefghijklmnopqrstuv

TELEGRAM_BOT_OWNER_ID = 1234567890

CLASH_OF_CLANS_API_LOGIN = login@example.com
CLASH_OF_CLANS_API_PASSWORD = 1234567890abcdef
CLASH_OF_CLANS_API_KEY_NAME = name
CLASH_OF_CLANS_API_KEY_DESCRIPTION = description

POSTGRES_HOST = https://host.example.com
POSTGRES_DATABASE = database
POSTGRES_SCHEMA = clashwardenbot
POSTGRES_USER = user
POSTGRES_PASSWORD = 1234567890abcdef

FREQUENT_JOBS_FREQUENCY_MINUTES = 1
INFREQUENT_JOBS_FREQUENCY_MINUTES = 10
JOB_TIMESPAN_SECONDS = 10

WEBHOOK_HOST = https://host.example.com
WEBHOOK_PATH = /path
WEBAPP_HOST = ::
WEBAPP_PORT = 1234

CLAN_TAGS = '["#1234567890"]'
TELEGRAM_BOT_API_TOKENS = '["1234567890:ABCDEFGHIJKLMNOPQRSTUVWXYZ123456789"]'

TOWN_HALL_EMOJI_IDS = '["5197380087128799912","5197265398617095220","5197340285666868975","5197615794934006616","5197676770584704648","5197477823404587838","5197513793755690795","5197300290931407279","5197425884365078232","5197371029042774532","5197396090176945787","5197313961812310251","5197163728151263266","5197412432527506000","5197603472672833857","5197190258164252027"]'
BUILDER_HALL_EMOJI_IDS = '["5197185288887089032","5197384742873348667","5197162327991925912","5197658349469973569","5197670899364412474","5197268508173417952","5197582057965894463","5197292259342564294","5197283252796144107","5197379756416319086"]'
HOME_VILLAGE_HERO_EMOJI_IDS = '["5194922180424516899","5197627129352699105","5197327744362363447","5197329312025425842"]'
CAPITAL_GOLD_EMOJI_ID = 5197204942657436620
RAID_MEDAL_EMOJI_ID = 5201914713599920485
```


## Usage

### Start long polling:

```bash
$ cd clashwardenbot
$ source .venv/bin/activate
$ python bot_polling.py --bot_number=0
```
```bot_number``` is the index of the corresponding values in ```clan_tags``` and ```telegram_bot_api_tokens``` lists from ```config.py```

## Deployment (systemd)

Every bot runs as its own systemd service `clashwardenbot@N`, where `N` is `bot_number`. Python 3.12 is installed by [uv](https://docs.astral.sh/uv/) and does not depend on the system Python. Logs go to the separate journald namespace `clashwardenbot`.

### First setup (as root)

```bash
curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin sh
useradd --system --create-home --home-dir /opt/clashwardenbot --shell /usr/sbin/nologin clashwardenbot
sudo -u clashwardenbot -H git clone -b dev https://github.com/mprokhorov/clashwardenbot /opt/clashwardenbot/app
cd /opt/clashwardenbot/app
sudo -u clashwardenbot -H uv venv --python 3.12
sudo -u clashwardenbot -H uv pip sync requirements.lock
install -o clashwardenbot -g clashwardenbot -m 600 /path/to/.env .env
cp deploy/*.service deploy/*.timer /etc/systemd/system/
cp deploy/journald@clashwardenbot.conf /etc/systemd/
systemctl daemon-reload
systemctl enable --now clashwardenbot@1 clashwardenbot-backup.timer clashwardenbot-restart.timer
```

### Everyday commands

```bash
/opt/clashwardenbot/app/deploy/update.sh       # git pull, sync dependencies, restart bots
journalctl --namespace=clashwardenbot -u clashwardenbot@1 -f  # follow logs of bot 1
systemctl status 'clashwardenbot@*'            # state of all bots
```

All bots are restarted daily at 00:00 by `clashwardenbot-restart.timer`. The log namespace is capped at 50 MB.

Database dumps are written daily to `/var/backups/clashwardenbot` and kept for 14 days. Restore: `pg_restore --clean -d <database> <file>.dump` as `postgres`.
