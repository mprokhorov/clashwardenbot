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
$ python -m venv .venv
$ source .venv/bin/activate
$ pip install -r requirements.txt
```
### Create PostgreSQL database

Use ```ddl.sql``` script to create schema ```public```


### Create and configure `.env` file

```
TELEGRAM_API_CLIENT_NAME = name
TELEGRAM_API_ID = 1234567890
TELEGRAM_API_HASH = 1234567890abcdefghijklmnopqrstuv

CLASH_OF_CLANS_API_LOGIN = login@example.com
CLASH_OF_CLANS_API_PASSWORD = 1234567890abcdef
CLASH_OF_CLANS_API_KEY_NAME = name
CLASH_OF_CLANS_API_KEY_DESCRIPTION = description

POSTGRES_HOST = https://host.example.com
POSTGRES_DATABASE = database
POSTGRES_SCHEMA = public
POSTGRES_USER = user
POSTGRES_PASSWORD = 1234567890abcdef

WEBHOOK_HOST = https://host.example.com
WEBHOOK_PATH = /path
WEBAPP_HOST = ::
WEBAPP_PORT = 1234

CLAN_TAGS = '["#1234567890"]'
TELEGRAM_BOT_API_TOKENS = '["1234567890:ABCDEFGHIJKLMNOPQRSTUVWXYZ123456789"]'

TELEGRAM_EMOJI_SET_NAME = Maxkiller_Emoji_pack
TOWN_HALL_EMOJI_IDS = '["5197380087128799912","5197265398617095220","5197340285666868975","5197615794934006616","5197676770584704648","5197477823404587838","5197513793755690795","5197300290931407279","5197425884365078232","5197371029042774532","5197396090176945787","5197313961812310251","5197163728151263266","5197412432527506000","5197603472672833857","5197190258164252027"]'
BUILDER_HALL_EMOJI_IDS = '["5197185288887089032","5197384742873348667","5197162327991925912","5197658349469973569","5197670899364412474","5197268508173417952","5197582057965894463","5197292259342564294","5197283252796144107","5197379756416319086"]'
HOME_VILLAGE_HERO_EMOJI_IDS = '["5194922180424516899","5197627129352699105","5197327744362363447","5197329312025425842"]'
CAPITAL_GOLD_EMOJI_ID = 5197204942657436620
RAID_MEDAL_EMOJI_ID = 5201914713599920485

TELEGRAM_BOT_OWNER_ID = 1234567890
BOT_COMMANDS = '["cw_info","cw_attacks","cw_map","cw_skips","cw_ping","cw_status","cw_list","raids_info","raids_loot","raids_skips","raids_ping","raids_analysis","cwl_info","cwl_attacks","cwl_map","cwl_skips","cwl_ping","cwl_clans","player_info","members","donations","contributions","events","admin","alert","ping"]'
```


## Usage

### Start long polling:

```bash
$ cd clashwardenbot
$ source .venv/bin/activate
$ python bot_polling.py --bot_number=0
```
```bot_number``` is the index of the corresponding values in ```clan_tags``` and ```telegram_bot_api_tokens``` lists from ```config.py```