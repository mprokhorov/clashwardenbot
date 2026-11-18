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

## Deployment

Production is controlled from a separate Telegram control bot: it chooses the deployed branch, the running bot instances (one per clan from `CLAN_TAGS`) and whether the ad script runs.

- `clashwardenbot@N` — bot with `bot_number=N`, runs as user `clashwardenbot` from `/opt/clashwardenbot/app` on Python 3.12 installed by [uv](https://docs.astral.sh/uv/)
- `clashwardenbot-deploy` — deployer (root). Every minute and right after any change in the panel it fetches git, deploys the chosen branch (`uv pip sync requirements.lock`), enables or disables instances and checks that the bots are alive
- `clashwardenbot-control` — control bot, runs as unprivileged user `clashwardenbot-control`, only edits `/var/lib/clashwardenbot-control/state.json` and reads the deployer status
- `clashwardenbot-restart.timer` — daily restart at 00:00, `clashwardenbot-backup.timer` — daily database dump to `/var/backups/clashwardenbot` (14 days)

Code that runs as root (deployer, backup) is copied to root-owned `/opt/clashwardenbot-control` and is never run from the deployed branch, so a broken branch cannot break the panel.

### Setup (as root)

Create the control bot in @BotFather, then:

```bash
curl -fsSL https://raw.githubusercontent.com/mprokhorov/clashwardenbot/dev/deploy/install.sh -o /root/install.sh
bash /root/install.sh --env /path/to/.env
```

The script is idempotent: run it again to update the control panel code and systemd units. The previous units are saved to `/etc/systemd/system/clashwardenbot-units-backup-*`.

### Useful commands

```bash
journalctl --namespace=clashwardenbot -u clashwardenbot@1 -f           # logs of bot 1
journalctl --namespace=clashwardenbot -u clashwardenbot-deploy -n 50    # deployer log
systemctl status 'clashwardenbot@*'                                     # state of all bots
```

Restore a database dump: `pg_restore --clean -d <database> <file>.dump` as `postgres`.
