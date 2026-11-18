#!/usr/bin/env python3
"""
Brings the production machine to the state chosen in the control bot.

Runs as root from clashwardenbot-deploy.service every minute and whenever the control bot changes state.json.
Uses only the standard library and Python 3.8 syntax, because it runs on the system Python.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from datetime import datetime, timezone

APP_USER = 'clashwardenbot'
APP_DIR = '/opt/clashwardenbot/app'
STATE_PATH = '/var/lib/clashwardenbot-control/state.json'
STATUS_PATH = '/var/lib/clashwardenbot-deploy/status.json'
UV = '/usr/local/bin/uv'
BOT_UNIT = 'clashwardenbot@{}.service'
AD_UNIT = 'clashwardenbot-ad.service'
HEALTH_CHECK_SECONDS = 20
MAX_EVENTS = 50
MAX_LOG_CHARS = 3500
BRANCH_NAME_PATTERN = re.compile(r'^[A-Za-z0-9._][A-Za-z0-9._/-]{0,99}$')
SQL_NAME_PATTERN = re.compile(r'^[A-Za-z_][A-Za-z0-9_]{0,62}$')


class DeployError(Exception):
    pass


log_lines = []


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def log(message: str) -> None:
    line = f'{datetime.now().strftime("%H:%M:%S")} {message}'
    print(line, flush=True)
    log_lines.append(line)


def run(args: list, as_app_user: bool = False, check: bool = True, cwd: str = '/') -> str:
    if as_app_user:
        args = ['runuser', '-u', APP_USER, '--'] + args
    result = subprocess.run(
        args, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True
    )
    if check and result.returncode != 0:
        raise DeployError(f'Команда «{" ".join(args)}» завершилась с ошибкой:\n{result.stdout.strip()[-1500:]}')
    return result.stdout.strip()


def git(*args: str) -> str:
    return run(['git', '-C', APP_DIR] + list(args), as_app_user=True)


def read_json(path: str) -> dict | None:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return None
    try:
        with os.fdopen(fd, encoding='utf-8') as file:
            data = json.load(file)
    except (OSError, ValueError):
        raise DeployError(f'Файл {path} повреждён')
    if not isinstance(data, dict):
        raise DeployError(f'Файл {path} повреждён')
    return data


def write_json(path: str, data: dict) -> None:
    tmp_path = os.path.join(os.path.dirname(path), f'.{os.path.basename(path)}.tmp')
    if os.path.lexists(tmp_path):
        os.unlink(tmp_path)
    fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
    with os.fdopen(fd, 'w', encoding='utf-8') as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)


def read_env(path: str) -> dict:
    values = {}
    with open(path, encoding='utf-8') as file:
        for line in file:
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, value = line.split('=', 1)
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in '\'"':
                value = value[1:-1]
            values[key.strip().upper()] = value
    return values


def load_clans(env: dict) -> list:
    clan_tags = json.loads(env.get('CLAN_TAGS', '[]'))
    clan_names = {}
    schema, database = env.get('POSTGRES_SCHEMA', ''), env.get('POSTGRES_DATABASE', '')
    if SQL_NAME_PATTERN.match(schema) and SQL_NAME_PATTERN.match(database):
        result = subprocess.run(
            ['runuser', '-u', 'postgres', '--', 'psql', '-d', database, '-At', '-F', '\t',
             '-c', f'SELECT clan_tag, clan_name FROM "{schema}".clan'],
            cwd='/', stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, universal_newlines=True
        )
        for line in result.stdout.splitlines():
            if '\t' in line:
                clan_tag, clan_name = line.split('\t', 1)
                clan_names[clan_tag] = clan_name
    return [
        {'number': number, 'tag': clan_tag, 'name': clan_names.get(clan_tag)}
        for number, clan_tag in enumerate(clan_tags)
    ]


def list_branches() -> list:
    output = git(
        'for-each-ref', 'refs/remotes/origin', '--sort=-committerdate',
        '--format=%(refname:lstrip=3)%09%(objectname)%09%(committerdate:unix)%09%(subject)'
    )
    branches = []
    for line in output.splitlines():
        name, sha, date, subject = (line.split('\t', 3) + [''])[:4]
        if name != 'HEAD':
            branches.append({'name': name, 'sha': sha, 'date': int(date), 'subject': subject})
    return branches


def head_info() -> dict:
    branch = git('rev-parse', '--abbrev-ref', 'HEAD')
    sha, date, subject = git('log', '-1', '--format=%H%x09%ct%x09%s').split('\t', 2)
    return {'branch': branch, 'sha': sha, 'date': int(date), 'subject': subject}


def sync_dependencies() -> None:
    if not os.path.exists(os.path.join(APP_DIR, '.venv')):
        run([UV, 'venv', '--quiet', '--python', '3.12', '.venv'], as_app_user=True, cwd=APP_DIR)
    if os.path.exists(os.path.join(APP_DIR, 'requirements.lock')):
        run([UV, 'pip', 'sync', '--quiet', '--python', '.venv/bin/python', 'requirements.lock'], as_app_user=True, cwd=APP_DIR)
    else:
        run([UV, 'pip', 'install', '--quiet', '--python', '.venv/bin/python', '-r', 'requirements.txt'], as_app_user=True, cwd=APP_DIR)


def checkout(branch: str, sha: str) -> None:
    if branch == 'HEAD':
        git('checkout', '--quiet', '--force', sha)
    else:
        git('checkout', '--quiet', '--force', '-B', branch, sha)


def unit_active_state(unit: str) -> str:
    return run(['systemctl', 'is-active', unit], check=False)


def is_unit_crashing(unit: str) -> bool:
    active_state, sub_state = (
        run(['systemctl', 'show', '-p', 'ActiveState', '-p', 'SubState', '--value', unit], check=False).split('\n') + ['']
    )[:2]
    return active_state == 'failed' or sub_state == 'auto-restart'


def is_unit_enabled(unit: str) -> bool:
    return run(['systemctl', 'is-enabled', unit], check=False) == 'enabled'


def is_unit_loaded(unit: str) -> bool:
    return run(['systemctl', 'show', '-p', 'LoadState', '--value', unit], check=False) == 'loaded'


def set_unit_enabled(unit: str, enabled: bool, restart: bool) -> None:
    if enabled:
        if not is_unit_enabled(unit):
            log(f'Включаю {unit}')
            run(['systemctl', 'enable', '--quiet', unit])
        if restart:
            run(['systemctl', 'restart', unit])
        elif unit_active_state(unit) != 'active':
            run(['systemctl', 'start', unit])
    elif is_unit_enabled(unit) or unit_active_state(unit) not in ['inactive', 'unknown']:
        log(f'Выключаю {unit}')
        run(['systemctl', 'disable', '--now', '--quiet', unit])


def apply_state(state: dict, status: dict, clans: list) -> None:
    branch = state.get('branch')
    if not isinstance(branch, str) or not BRANCH_NAME_PATTERN.match(branch):
        raise DeployError('В state.json указана некорректная ветка')
    remote_branches = {remote_branch['name']: remote_branch for remote_branch in status['branches']}
    if branch not in remote_branches:
        raise DeployError(f'Ветка {branch} не найдена на GitHub')
    current = head_info()
    target_sha = remote_branches[branch]['sha']
    deploy_request = state.get('deploy_request', 0)
    restart_request = state.get('restart_request', 0)
    is_deploy_requested = deploy_request != status.get('deploy_request_handled', 0)
    need_restart = restart_request != status.get('restart_request_handled', 0)
    if current['branch'] != branch or (
            current['sha'] != target_sha and (state.get('auto_update', True) or is_deploy_requested)
    ):
        log(f'Выкатываю {branch} {target_sha[:7]} (было {current["branch"]} {current["sha"][:7]})')
        checkout(branch, target_sha)
        try:
            sync_dependencies()
        except DeployError:
            log(f'Не удалось установить зависимости, возвращаю {current["branch"]} {current["sha"][:7]}')
            checkout(current['branch'], current['sha'])
            sync_dependencies()
            raise
        need_restart = True
        deployed = head_info()
        add_event(status, 'deployed', f'Выкачена ветка {branch}: {deployed["sha"][:7]} {deployed["subject"]}')
    status['deploy_request_handled'] = deploy_request
    status['restart_request_handled'] = restart_request

    wanted_numbers = {number for number in state.get('instances', []) if isinstance(number, int)}
    restarted_numbers = []
    for clan in clans:
        unit = BOT_UNIT.format(clan['number'])
        is_wanted = clan['number'] in wanted_numbers
        set_unit_enabled(unit, is_wanted, need_restart)
        if is_wanted and need_restart:
            restarted_numbers.append(clan['number'])
    if restarted_numbers:
        log(f'Перезапущены боты: {", ".join(map(str, restarted_numbers))}')

    if isinstance(state.get('ad_enabled'), bool) and is_unit_loaded(AD_UNIT):
        set_unit_enabled(AD_UNIT, state['ad_enabled'], False)

    if restarted_numbers:
        time.sleep(HEALTH_CHECK_SECONDS)
    failed_numbers = [
        clan['number'] for clan in clans
        if clan['number'] in wanted_numbers and (
            is_unit_crashing(BOT_UNIT.format(clan['number']))
            or clan['number'] in restarted_numbers and unit_active_state(BOT_UNIT.format(clan['number'])) != 'active'
        )
    ]
    if failed_numbers:
        raise DeployError(
            f'Не работают боты: {", ".join(map(str, failed_numbers))}. '
            f'Логи: journalctl --namespace=clashwardenbot -u clashwardenbot@{failed_numbers[0]}'
        )


def add_event(status: dict, kind: str, text: str) -> None:
    status['event_id'] = status.get('event_id', 0) + 1
    status['events'] = (status.get('events', []) + [
        {'id': status['event_id'], 'at': utc_now(), 'kind': kind, 'text': text}
    ])[-MAX_EVENTS:]


def main() -> None:
    try:
        status = read_json(STATUS_PATH) or {}
    except DeployError:
        status = {}
    previous_error = status.get('error')
    error = None
    try:
        clans = load_clans(read_env(os.path.join(APP_DIR, '.env')))
        status['clans'] = clans
        git('fetch', '--quiet', '--prune', 'origin')
        status['branches'] = list_branches()
        state = read_json(STATE_PATH)
        if state is not None:
            apply_state(state, status, clans)
    except DeployError as e:
        error = str(e)
        log(error)
    except Exception as e:
        error = f'Непредвиденная ошибка деплоера: {e!r}'
        log(error)
    try:
        status['deployed'] = head_info()
    except DeployError:
        pass
    if error is not None and error != previous_error:
        add_event(status, 'error', error)
    elif error is None and previous_error is not None:
        add_event(status, 'recovered', 'Ошибка устранена, прод в порядке')
    status['error'] = error
    status['checked_at'] = utc_now()
    if log_lines:
        status['log'] = '\n'.join(log_lines)[-MAX_LOG_CHARS:]
        status['log_at'] = utc_now()
    write_json(STATUS_PATH, status)


if __name__ == '__main__':
    main()
