# clashwardenbot

Link to an example of bot: [t.me/clashwardenbot](https://t.me/clashwardenbot)

## Requirements

- Python 3.12

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

### Configure `.env` file

## Usage

### Start long polling:

```bash
$ cd clashwardenbot
$ source .venv/bin/activate
$ python bot_polling.py --bot_number=0
```
```bot_number``` is the index of the corresponding values in ```clan_tags``` and ```telegram_bot_api_tokens``` lists from ```config.py```