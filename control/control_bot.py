"""
Control panel bot for the production machine.

Only edits state.json (the desired production state) and reads status.json written by the deployer, so it needs
no privileges. Runs from its own copy of the code and keeps working even if the deployed branch is broken.
"""
import asyncio
import hashlib
import html
import json
import logging
import os
from contextlib import suppress
from datetime import datetime
from typing import Optional

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.filters.callback_data import CallbackData
from aiogram.types import BotCommand, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

STATE_PATH = '/var/lib/clashwardenbot-control/state.json'
STATUS_PATH = '/var/lib/clashwardenbot-deploy/status.json'
BOT_UNIT = 'clashwardenbot@{}.service'
AD_UNIT = 'clashwardenbot-ad.service'
NOTIFY_INTERVAL_SECONDS = 15

TOKEN = os.environ['CONTROL_BOT_TOKEN']
OWNER_ID = int(os.environ['CONTROL_BOT_OWNER_ID'])

router = Router()
router.message.filter(F.from_user.id == OWNER_ID)
router.callback_query.filter(F.from_user.id == OWNER_ID)


class PanelCallbackFactory(CallbackData, prefix='panel'):
    action: str
    arg: Optional[str] = None


def read_json(path: str) -> dict:
    try:
        with open(path, encoding='utf-8') as file:
            return json.load(file)
    except (OSError, ValueError):
        return {}


def write_state(state: dict) -> None:
    tmp_path = f'{STATE_PATH}.tmp'
    with open(tmp_path, 'w', encoding='utf-8') as file:
        json.dump(state, file, ensure_ascii=False, indent=2)
    os.replace(tmp_path, STATE_PATH)


def branch_key(branch: str) -> str:
    return hashlib.sha1(branch.encode()).hexdigest()[:10]


def short_datetime(value) -> str:
    if isinstance(value, int):
        dt = datetime.fromtimestamp(value)
    else:
        dt = datetime.fromisoformat(value).astimezone()
    return dt.strftime('%d.%m %H:%M')


async def get_unit_states(units: list[str]) -> dict[str, tuple[str, str]]:
    process = await asyncio.create_subprocess_exec(
        'systemctl', 'show', '-p', 'Id', '-p', 'LoadState', '-p', 'ActiveState', '-p', 'SubState', *units,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
    )
    stdout, _ = await process.communicate()
    unit_states = {}
    for block in stdout.decode().strip().split('\n\n'):
        properties = dict(line.split('=', 1) for line in block.splitlines() if '=' in line)
        if 'Id' in properties:
            unit_states[properties['Id']] = (
                properties.get('ActiveState', 'unknown') if properties.get('LoadState') == 'loaded' else 'not-found',
                properties.get('SubState', '')
            )
    return unit_states


def unit_state_to_text(active_state: str, sub_state: str, is_wanted: bool) -> tuple[str, str]:
    if active_state == 'active':
        return ('🟢', 'работает') if is_wanted else ('🟠', 'работает, но выключен в пульте')
    if active_state == 'failed' or sub_state == 'auto-restart':
        return '🔴', 'падает'
    if active_state in ['activating', 'reloading']:
        return '🟡', 'запускается'
    if active_state == 'deactivating':
        return '🟡', 'останавливается'
    return ('⏳', 'ждёт запуска') if is_wanted else ('⚪', 'выключен')


def clan_title(clan: dict) -> str:
    return f'#{clan['number']} {clan.get('name') or clan['tag']}'


async def panel() -> tuple[str, InlineKeyboardMarkup]:
    state, status = read_json(STATE_PATH), read_json(STATUS_PATH)
    clans = status.get('clans', [])
    wanted_numbers = set(state.get('instances', []))
    unit_states = await get_unit_states([BOT_UNIT.format(clan['number']) for clan in clans] + [AD_UNIT])
    deployed = status.get('deployed', {})
    text = (
        f'<b>🎛️ Пульт ClashWardenBot</b>\n'
        f'\n'
        f'Ветка: <b>{html.escape(state.get('branch', '—'))}</b>\n'
    )
    if deployed:
        text += (
            f'Выкачено: {html.escape(deployed['branch'])} <code>{deployed['sha'][:7]}</code> '
            f'{html.escape(deployed['subject'])} ({short_datetime(deployed['date'])})\n'
        )
    text += f'Автообновление: {'✅' if state.get('auto_update', True) else '❌'}\n'
    if status.get('checked_at'):
        text += f'Проверено: {short_datetime(status['checked_at'])}\n'
    pending = []
    if deployed and state.get('branch') != deployed.get('branch'):
        pending.append(f'переключение на {html.escape(state['branch'])}')
    if state.get('deploy_request', 0) != status.get('deploy_request_handled', 0):
        pending.append('выкат')
    if state.get('restart_request', 0) != status.get('restart_request_handled', 0):
        pending.append('перезапуск')
    if pending:
        text += f'⏳ Применяется: {', '.join(pending)}\n'
    text += f'\nБоты:\n'
    button_rows = []
    bot_buttons = []
    for clan in clans:
        is_wanted = clan['number'] in wanted_numbers
        emoji, description = unit_state_to_text(*unit_states.get(BOT_UNIT.format(clan['number']), ('unknown', '')), is_wanted)
        text += f'{emoji} {html.escape(clan_title(clan))} — {description}\n'
        bot_buttons.append(InlineKeyboardButton(
            text=f'{'🟢' if is_wanted else '⚪'} {clan_title(clan)}',
            callback_data=PanelCallbackFactory(action='bot', arg=str(clan['number'])).pack()
        ))
    if len(clans) == 0:
        text += 'Нет данных от деплоера\n'
    button_rows += [bot_buttons[i:i + 2] for i in range(0, len(bot_buttons), 2)]
    ad_active_state, ad_sub_state = unit_states.get(AD_UNIT, ('not-found', ''))
    if ad_active_state != 'not-found':
        is_ad_wanted = state.get('ad_enabled', False)
        emoji, description = unit_state_to_text(ad_active_state, ad_sub_state, is_ad_wanted)
        text += f'\nРеклама: {emoji} {description}\n'
        button_rows.append([InlineKeyboardButton(
            text=f'📣 {'Выключить' if is_ad_wanted else 'Включить'} рекламу',
            callback_data=PanelCallbackFactory(action='ad').pack()
        )])
    if status.get('error'):
        text += f'\n⚠️ <b>Ошибка:</b>\n<pre>{html.escape(status['error'])}</pre>\n'
    button_rows += [
        [
            InlineKeyboardButton(
                text=f'🌿 Ветка: {state.get('branch', '—')}',
                callback_data=PanelCallbackFactory(action='branches').pack()
            ),
            InlineKeyboardButton(
                text=f'🔁 {'Выключить' if state.get('auto_update', True) else 'Включить'} автообновление',
                callback_data=PanelCallbackFactory(action='auto').pack()
            )
        ],
        [
            InlineKeyboardButton(text='⬇️ Выкатить сейчас', callback_data=PanelCallbackFactory(action='deploy').pack()),
            InlineKeyboardButton(text='♻️ Перезапустить ботов', callback_data=PanelCallbackFactory(action='restart').pack())
        ],
        [
            InlineKeyboardButton(text='📜 Журнал', callback_data=PanelCallbackFactory(action='log').pack()),
            InlineKeyboardButton(text='🔄 Обновить', callback_data=PanelCallbackFactory(action='main').pack())
        ]
    ]
    return text, InlineKeyboardMarkup(inline_keyboard=button_rows)


def branches_view() -> tuple[str, InlineKeyboardMarkup]:
    state, status = read_json(STATE_PATH), read_json(STATUS_PATH)
    text = (
        f'<b>🌿 Выбор ветки</b>\n'
        f'\n'
        f'Сейчас: <b>{html.escape(state.get('branch', '—'))}</b>\n'
        f'\n'
        f'Выберите ветку:'
    )
    button_rows = [[InlineKeyboardButton(
        text=f'{'✅ ' if branch['name'] == state.get('branch') else ''}{branch['name']} · '
             f'{branch['sha'][:7]} · {short_datetime(branch['date'])}',
        callback_data=PanelCallbackFactory(action='branch', arg=branch_key(branch['name'])).pack()
    )] for branch in status.get('branches', [])]
    button_rows.append([
        InlineKeyboardButton(text='⬅️ Назад', callback_data=PanelCallbackFactory(action='main').pack()),
        InlineKeyboardButton(text='🔄 Обновить', callback_data=PanelCallbackFactory(action='branches').pack())
    ])
    return text, InlineKeyboardMarkup(inline_keyboard=button_rows)


def find_branch(key: str) -> Optional[dict]:
    return next((
        branch for branch in read_json(STATUS_PATH).get('branches', []) if branch_key(branch['name']) == key
    ), None)


def confirm_branch_view(branch: dict) -> tuple[str, InlineKeyboardMarkup]:
    text = (
        f'<b>🌿 Переключить прод на ветку {html.escape(branch['name'])}?</b>\n'
        f'\n'
        f'Последний коммит: <code>{branch['sha'][:7]}</code> {html.escape(branch['subject'])} '
        f'({short_datetime(branch['date'])})\n'
        f'\n'
        f'Все включённые боты будут перезапущены.'
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text='⬅️ Назад', callback_data=PanelCallbackFactory(action='branches').pack()),
        InlineKeyboardButton(
            text='✅ Переключить', callback_data=PanelCallbackFactory(action='confirm', arg=branch_key(branch['name'])).pack()
        )
    ]])
    return text, keyboard


def log_view() -> tuple[str, InlineKeyboardMarkup]:
    status = read_json(STATUS_PATH)
    text = f'<b>📜 Журнал деплоя</b>\n\n'
    if status.get('log'):
        text += f'Последние действия ({short_datetime(status['log_at'])}):\n<pre>{html.escape(status['log'])}</pre>'
    else:
        text += 'Журнал пуст'
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text='⬅️ Назад', callback_data=PanelCallbackFactory(action='main').pack()),
        InlineKeyboardButton(text='🔄 Обновить', callback_data=PanelCallbackFactory(action='log').pack())
    ]])
    return text, keyboard


@router.message(Command('start', 'panel'))
async def command_panel(message: Message) -> None:
    text, keyboard = await panel()
    await message.answer(text=text, reply_markup=keyboard)


@router.callback_query(PanelCallbackFactory.filter())
async def callback_panel(callback_query: CallbackQuery, callback_data: PanelCallbackFactory) -> None:
    state = read_json(STATE_PATH)
    answer_text = None
    if callback_data.action == 'bot':
        number = int(callback_data.arg)
        instances = set(state.get('instances', []))
        instances ^= {number}
        state['instances'] = sorted(instances)
        write_state(state)
        answer_text = f'Бот #{number} {'включается' if number in instances else 'выключается'}'
    elif callback_data.action == 'ad':
        state['ad_enabled'] = not state.get('ad_enabled', False)
        write_state(state)
        answer_text = f'Реклама {'включается' if state['ad_enabled'] else 'выключается'}'
    elif callback_data.action == 'auto':
        state['auto_update'] = not state.get('auto_update', True)
        write_state(state)
        answer_text = f'Автообновление {'включено' if state['auto_update'] else 'выключено'}'
    elif callback_data.action == 'deploy':
        state['deploy_request'] = state.get('deploy_request', 0) + 1
        write_state(state)
        answer_text = 'Выкат запущен'
    elif callback_data.action == 'restart':
        state['restart_request'] = state.get('restart_request', 0) + 1
        write_state(state)
        answer_text = 'Перезапуск запущен'
    elif callback_data.action == 'confirm':
        branch = find_branch(callback_data.arg)
        if branch is None:
            answer_text = 'Ветка не найдена'
        else:
            state['branch'] = branch['name']
            write_state(state)
            answer_text = f'Переключаю на {branch['name']}'

    if callback_data.action == 'branches':
        text, keyboard = branches_view()
    elif callback_data.action == 'branch' and find_branch(callback_data.arg) is not None:
        text, keyboard = confirm_branch_view(find_branch(callback_data.arg))
    elif callback_data.action == 'log':
        text, keyboard = log_view()
    else:
        text, keyboard = await panel()
    with suppress(TelegramBadRequest):
        await callback_query.message.edit_text(text=text, reply_markup=keyboard)
    await callback_query.answer(answer_text or ('Сообщение обновлено' if callback_data.action == 'main' else None))


async def notify_owner(bot: Bot) -> None:
    last_event_id = read_json(STATUS_PATH).get('event_id', 0)
    crashing_numbers = set()
    while True:
        await asyncio.sleep(NOTIFY_INTERVAL_SECONDS)
        try:
            state, status = read_json(STATE_PATH), read_json(STATUS_PATH)
            messages = []
            for event in status.get('events', []):
                if event['id'] > last_event_id:
                    emoji = {'deployed': '⬇️', 'error': '⚠️', 'recovered': '✅'}.get(event['kind'], '💬')
                    messages.append(f'{emoji} {html.escape(event['text'])}')
            last_event_id = max([last_event_id] + [event['id'] for event in status.get('events', [])])
            clans = status.get('clans', [])
            unit_states = await get_unit_states([BOT_UNIT.format(clan['number']) for clan in clans])
            for clan in clans:
                if clan['number'] not in state.get('instances', []):
                    crashing_numbers.discard(clan['number'])
                    continue
                active_state, sub_state = unit_states.get(BOT_UNIT.format(clan['number']), ('unknown', ''))
                is_crashing = active_state == 'failed' or sub_state == 'auto-restart'
                if is_crashing and clan['number'] not in crashing_numbers:
                    messages.append(f'🔴 Бот {html.escape(clan_title(clan))} падает')
                    crashing_numbers.add(clan['number'])
                elif active_state == 'active' and clan['number'] in crashing_numbers:
                    messages.append(f'🟢 Бот {html.escape(clan_title(clan))} снова работает')
                    crashing_numbers.discard(clan['number'])
            for message_text in messages:
                await bot.send_message(chat_id=OWNER_ID, text=message_text)
        except Exception:
            logging.exception('Notification loop failed')


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format='%(filename)s:%(lineno)d #%(levelname)s - %(message)s')
    bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(router)
    await bot.set_my_commands([BotCommand(command='panel', description='🎛️ Пульт управления продом')])
    notify_task = asyncio.create_task(notify_owner(bot))
    try:
        await dp.start_polling(bot)
    finally:
        notify_task.cancel()


if __name__ == '__main__':
    asyncio.run(main())
