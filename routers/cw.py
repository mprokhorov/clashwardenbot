from contextlib import suppress
from datetime import datetime
from typing import Optional

from aiogram import Router
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.filters.callback_data import CallbackData
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton, InlineKeyboardMarkup
from magic_filter import F

from database_manager import DatabaseManager
from output_formatter.output_formatter import Event

router = Router()


class CWCallbackFactory(CallbackData, prefix='cw'):
    state: str
    tag: Optional[str] = None
    status: Optional[str] = None
    clan_war_start_time: Optional[datetime] = None


async def cw_info(dm: DatabaseManager, clan_war_start_time):
    cw = await dm.get_clan_war(clan_war_start_time=clan_war_start_time)
    answer = (f'<b>📃 Информация о КВ</b>\n'
              f'\n')
    if cw['state'] == 'preparation':
        answer += (f'{dm.of.to_html(cw['clan']['name'])} vs {dm.of.to_html(cw['opponent']['name'])}\n'
                   f'{cw['teamSize']} 👤 vs {cw['teamSize']} 👤\n'
                   f'\n'
                   f'{dm.of.event_datetime(Event.CW, cw['startTime'], cw['endTime'], True)}')
    elif cw['state'] == 'inWar':
        answer += (f'{dm.of.to_html(cw['clan']['name'])} vs {dm.of.to_html(cw['opponent']['name'])}\n'
                   f'{cw['teamSize']} 👤 vs {cw['teamSize']} 👤\n'
                   f'{cw['clan']['attacks']} 🗡 vs {cw['opponent']['attacks']} 🗡\n'
                   f'{cw['clan']['stars']} ⭐ vs {cw['opponent']['stars']} ⭐\n'
                   f'{format(cw['clan']['destructionPercentage'], '.2f')}% vs '
                   f'{format(cw['opponent']['destructionPercentage'], '.2f')}%\n'
                   f'\n'
                   f'{dm.of.event_datetime(Event.CW, cw['startTime'], cw['endTime'], True)}')
    elif cw['state'] == 'warEnded':
        answer += (f'{dm.of.to_html(cw['clan']['name'])} vs {dm.of.to_html(cw['opponent']['name'])}\n'
                   f'{cw['teamSize']} 👤 vs {cw['teamSize']} 👤\n'
                   f'{cw['clan']['attacks']} 🗡 vs {cw['opponent']['attacks']} 🗡\n'
                   f'{cw['clan']['stars']} ⭐ vs {cw['opponent']['stars']} ⭐\n'
                   f'{format(cw['clan']['destructionPercentage'], '.2f')}% vs '
                   f'{format(cw['opponent']['destructionPercentage'], '.2f')}%\n'
                   f'\n'
                   f'{dm.of.event_datetime(Event.CW, cw['startTime'], cw['endTime'], True)}\n'
                   f'\n')
        if (cw['clan']['stars'], cw['clan']['destructionPercentage']) > (
                cw['opponent']['stars'], cw['opponent']['destructionPercentage']):
            answer += f'🎉 Победа!'
        elif (cw['clan']['stars'], cw['clan']['destructionPercentage']) < (
                cw['opponent']['stars'], cw['opponent']['destructionPercentage']):
            answer += f'😢 Поражение'
        else:
            answer += f'⚖️ Ничья'
    else:
        answer += f'В данный момент война не идёт\n'
    return answer, ParseMode.HTML, None


@router.message(Command('cw_info'))
async def command_cw_info(message: Message, dm: DatabaseManager) -> None:
    answer, parse_mode, reply_markup = await cw_info(dm, await dm.clan_war_start_time(only_last=True))
    await message.reply(text=answer, parse_mode=parse_mode, reply_markup=reply_markup)


async def cw_attacks(dm: DatabaseManager):
    cw = await dm.get_clan_war(clan_war_start_time=await dm.clan_war_start_time(only_last=True))
    answer = (f'<b>🗡️ Атаки в КВ</b>\n'
              f'\n')
    if cw['state'] in ['preparation']:
        answer += f'{cw['clan']['name']} vs {cw['opponent']['name']}\n'
        answer += (f'{dm.of.event_datetime(Event.CW, cw['startTime'], cw['endTime'], False)}\n'
                   f'\n')
        answer += f'Список участников:\n'
        query = await dm.req_connection.fetch('''
            SELECT tag, name, town_hall, barbarian_king, archer_queen, grand_warden, royal_champion
            FROM public.clash_of_clans_account
        ''')
        desc = {record['tag']: (f'{dm.of.to_html(record['name'])} — 🛖 {record['town_hall']}, '
                                f'👑 {record['barbarian_king']} / {record['archer_queen']} / {record['grand_warden']} / '
                                f'{record['royal_champion']}')
                for record in query}
        clan_position = {}
        for member in cw['clan']['members']:
            clan_position[member['tag']] = member['mapPosition']
        output_strings = [''] * len(clan_position)
        for member in cw['clan']['members']:
            output_strings[clan_position[member['tag']] - 1] = (
                f'{clan_position[member['tag']]}) {desc.get(member['tag']) or dm.of.to_html(member['name'])}'
            )
        answer += '\n'.join(output_strings)
    elif cw['state'] in ['inWar', 'warEnded']:
        answer += f'{cw['clan']['name']} vs {cw['opponent']['name']}\n'
        answer += (f'{dm.of.event_datetime(Event.CW, cw['startTime'], cw['endTime'], False)}\n'
                   f'\n')
        clan_position = {}
        for member in cw['clan']['members']:
            clan_position[member['tag']] = member['mapPosition']
        opponent_position = {}
        for member in cw['opponent']['members']:
            opponent_position[member['tag']] = member['mapPosition']
        output_strings = [''] * len(clan_position)
        for member in cw['clan']['members']:
            attacks_count = 0
            if 'attacks' in member.keys():
                attacks_count += len(member['attacks'])
            output_strings[clan_position[member['tag']] - 1] += \
                f'{clan_position[member['tag']]}) {dm.of.to_html(member['name'])} — {attacks_count} / 2\n'
            if 'attacks' in member.keys():
                for attack in member['attacks']:
                    if attack['stars'] != 0:
                        output_strings[clan_position[member['tag']] - 1] += \
                            (f'{'⭐' * attack['stars']} ({attack['destructionPercentage']}%) '
                             f'➡️ {opponent_position[attack['defenderTag']]}\n')
                    else:
                        output_strings[clan_position[member['tag']] - 1] += \
                            (f'{attack['destructionPercentage']}% '
                             f'➡️ {opponent_position[attack['defenderTag']]}\n')
        answer += '\n'.join(output_strings)
    else:
        answer += f'В данный момент война не идёт\n'
    return answer, ParseMode.HTML, None


@router.message(Command('cw_attacks'))
async def command_cw_attacks(message: Message, dm: DatabaseManager) -> None:
    answer, parse_mode, reply_markup = await cw_attacks(dm)
    await message.reply(text=answer, parse_mode=parse_mode, reply_markup=reply_markup)


async def cw_status(dm: DatabaseManager, message: Message):
    query = await dm.req_connection.fetch('''
        SELECT tag, name, participates_in_clan_wars
        FROM
            public.tg_user_coc_account
            JOIN public.clash_of_clans_account USING (tag)
        WHERE id = $1
        ORDER by name
    ''', message.from_user.id)
    if len(query) == 0:
        answer = f'<b>✍🏻 Изменение статуса участия в КВ</b>\n\n'
        keyboard = None
        answer += f'Вашего аккаунта Clash of Clans нет в базе данных'
    elif len(query) == 1:
        record = query[0]
        answer, parse_mode, keyboard = await cw_status_set_status(dm, record['tag'])
    else:
        answer = f'<b>✍🏻 Изменение статуса участия в КВ</b>\n\n'
        answer += f'Выберите аккаунт:'
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=dm.of.to_html(record['name']),
                                  callback_data=CWCallbackFactory(
                                      state='cw_status_set_status',
                                      tag=record['tag']
                                  ).pack())]
            for record in query
        ])
    return answer, ParseMode.HTML, keyboard


@router.message(Command('cw_status'))
async def command_cw_status(message: Message, dm: DatabaseManager) -> None:
    answer, parse_mode, reply_markup = await cw_status(dm, message)
    reply_from_bot = await message.reply(text=answer, parse_mode=parse_mode, reply_markup=reply_markup)
    await dm.register_message(reply_from_bot.chat.id, reply_from_bot.message_id, message.from_user.id)


async def cw_status_set_status(dm: DatabaseManager, tag: str):
    query = await dm.req_connection.fetch('''
        SELECT name, participates_in_clan_wars
        FROM public.clash_of_clans_account
        WHERE tag = $1
    ''', tag)
    record = query[0]
    name, participates_in_clan_wars = record['name'], record['participates_in_clan_wars']
    if participates_in_clan_wars:
        participates_in_clan_wars_text = 'участвует'
        status_button_text = 'Не участвовать'
        status_future = 'false'
        status_current = 'true'
    else:
        participates_in_clan_wars_text = 'не участвует'
        status_button_text = 'Участвовать'
        status_future = 'true'
        status_current = 'false'
    answer = f'<b>✍🏻 Изменение статуса участия в КВ</b>\n\n'
    answer += f'Сейчас аккаунт {dm.of.to_html(name)} {participates_in_clan_wars_text} в КВ'
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=status_button_text,
                             callback_data=CWCallbackFactory(
                                 state='cw_status_finish',
                                 tag=tag,
                                 status=status_future
                             ).pack()),
        InlineKeyboardButton(text='Не менять статус',
                             callback_data=CWCallbackFactory(
                                 state='cw_status_finish',
                                 tag=tag,
                                 status=status_current
                             ).pack())
        ]])
    return answer, ParseMode.HTML, keyboard


@router.callback_query(CWCallbackFactory.filter(F.state == 'cw_status_set_status'))
async def callback_cw_status(callback: CallbackQuery, callback_data: CWCallbackFactory,
                             dm: DatabaseManager) -> None:
    user_is_message_owner = await dm.check_message(callback.message.chat.id,
                                                   callback.message.message_id,
                                                   callback.from_user.id)
    if not user_is_message_owner:
        await callback.answer('Эта кнопка не для вас!')
    else:
        answer, parse_mode, reply_markup = await cw_status_set_status(dm, callback_data.tag)
        await callback.message.edit_text(text=answer, parse_mode=parse_mode, reply_markup=reply_markup)
        await callback.answer()


async def cw_status_finish(dm: DatabaseManager, tag: str, status: str):
    await dm.req_connection.execute('''
        UPDATE public.clash_of_clans_account
        SET participates_in_clan_wars = $1
        WHERE tag = $2
    ''', status == 'true', tag)
    answer = f'<b>✍🏻 Изменение статуса участия в КВ</b>\n\n'
    query = await dm.req_connection.fetch('''
        SELECT name, participates_in_clan_wars
        FROM public.clash_of_clans_account
        WHERE tag = $1
    ''', tag)
    record = query[0]
    name, participates_in_clan_wars = record['name'], record['participates_in_clan_wars']
    if participates_in_clan_wars:
        participates_in_clan_wars_text = 'участвует'
    else:
        participates_in_clan_wars_text = 'не участвует'
    answer += f'Аккаунт {dm.of.to_html(name)} {participates_in_clan_wars_text} в КВ'
    return answer, ParseMode.HTML, None


@router.callback_query(CWCallbackFactory.filter(F.state == 'cw_status_finish'))
async def callback_cw_status(callback: CallbackQuery, callback_data: CWCallbackFactory,
                             dm: DatabaseManager) -> None:
    user_is_message_owner = await dm.check_message(callback.message.chat.id,
                                                   callback.message.message_id,
                                                   callback.from_user.id)
    if not user_is_message_owner:
        await callback.answer('Эта кнопка не для вас!')
    else:
        answer, parse_mode, reply_markup = await cw_status_finish(dm, callback_data.tag, callback_data.status)
        with suppress(TelegramBadRequest):
            await callback.message.edit_text(text=answer, parse_mode=parse_mode, reply_markup=reply_markup)
            await callback.answer()


async def cw_list_default(dm: DatabaseManager):
    query = await dm.req_connection.fetch('''
        SELECT tag, name, town_hall, barbarian_king, archer_queen, grand_warden, royal_champion
        FROM public.clash_of_clans_account
        WHERE participates_in_clan_wars
        ORDER BY town_hall DESC, (barbarian_king + archer_queen + grand_warden + royal_champion) DESC
    ''')
    answer = f'<b>📋 Список участников КВ (⬇️ по ТХ и героям)</b>\n\n'
    keyboard = None
    if len(query) > 0:
        for i, record in enumerate(query):
            answer += (f'{i + 1}) {dm.of.to_html(record['name'])} — 🛖 {record['town_hall']}, '
                       f'👑 {record['barbarian_king']} / {record['archer_queen']} / '
                       f'{record['grand_warden']} / {record['royal_champion']}\n')
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text='⬇️ по трофеям',
                                 callback_data=CWCallbackFactory(
                                     state='cw_list_trophies'
                                 ).pack())
        ]])
    else:
        answer += 'Список пуст'
    return answer, ParseMode.HTML, keyboard


async def cw_list_trophies(dm: DatabaseManager):
    query = await dm.req_connection.fetch('''
        SELECT tag, name, town_hall, barbarian_king, archer_queen, grand_warden, royal_champion
        FROM public.clash_of_clans_account
        WHERE participates_in_clan_wars
        ORDER BY trophies DESC
    ''')
    answer = f'<b>📋 Список участников КВ (⬇️ по трофеям)</b>\n\n'
    keyboard = None
    if len(query) > 0:
        for i, record in enumerate(query):
            answer += (f'{i + 1}) {dm.of.to_html(record['name'])} — 🛖 {record['town_hall']}, '
                       f'👑 {record['barbarian_king']} / {record['archer_queen']} / '
                       f'{record['grand_warden']} / {record['royal_champion']}\n')
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text='⬇️ по ТХ и героям',
                                 callback_data=CWCallbackFactory(
                                     state='cw_list_default'
                                 ).pack())
        ]])
    else:
        answer += 'Список пуст'
    return answer, ParseMode.HTML, keyboard


@router.message(Command('cw_list'))
async def command_cw_list(message: Message, dm: DatabaseManager) -> None:
    answer, parse_mode, reply_markup = await cw_list_default(dm)
    reply_from_bot = await message.reply(text=answer, parse_mode=parse_mode, reply_markup=reply_markup)
    await dm.register_message(reply_from_bot.chat.id, reply_from_bot.message_id, message.from_user.id)


@router.callback_query(CWCallbackFactory.filter(F.state == 'cw_list_trophies'))
async def callback_cw_list(callback: CallbackQuery, callback_data: CWCallbackFactory,
                           dm: DatabaseManager) -> None:
    user_is_message_owner = await dm.check_message(callback.message.chat.id,
                                                   callback.message.message_id,
                                                   callback.from_user.id)
    if not user_is_message_owner:
        await callback.answer('Эта кнопка не для вас!')
    else:
        answer, parse_mode, reply_markup = await cw_list_trophies(dm)
        with suppress(TelegramBadRequest):
            await callback.message.edit_text(text=answer, parse_mode=parse_mode, reply_markup=reply_markup)
            await callback.answer()


@router.callback_query(CWCallbackFactory.filter(F.state == 'cw_list_default'))
async def callback_cw_list(callback: CallbackQuery, callback_data: CWCallbackFactory,
                           dm: DatabaseManager) -> None:
    user_is_message_owner = await dm.check_message(callback.message.chat.id,
                                                   callback.message.message_id,
                                                   callback.from_user.id)
    if not user_is_message_owner:
        await callback.answer('Эта кнопка не для вас!')
    else:
        answer, parse_mode, reply_markup = await cw_list_default(dm)
        with suppress(TelegramBadRequest):
            await callback.message.edit_text(text=answer, parse_mode=parse_mode, reply_markup=reply_markup)
            await callback.answer()


async def cw_skips(dm: DatabaseManager, ping: bool):
    cw = await dm.get_clan_war(clan_war_start_time=await dm.clan_war_start_time(only_last=True))
    answer = f'<b>🙈 Список не проатаковавших в КВ</b>\n\n'
    if cw['state'] in ['inWar', 'warEnded']:
        answer += f'❗ {dm.of.event_datetime(Event.CW, cw['startTime'], cw['endTime'], False)}\n\n'
        query = await dm.req_connection.fetch('''
            SELECT tag, name, id, first_name, last_name
            FROM
                public.tg_user_coc_account
                JOIN public.telegram_user USING (id)
                JOIN public.clash_of_clans_account USING (tag)
        ''')
        coc_accounts_names = {record['tag']: record['name'] for record in query}
        users_whose_coc_accounts_are_mentioned = {record['id']: [] for record in query}
        unlinked_coc_accounts = []
        tg_users_linked_to_coc_account = {tag: [] for tag in coc_accounts_names}
        tg_users = {record['id']: {'first_name': record['first_name'], 'last_name': record['last_name']}
                    for record in query}
        for record in query:
            tg_users_linked_to_coc_account[record['tag']].append(record['id'])
        for cw_member in cw['clan']['members']:
            cw_member_attacks = 0 if 'attacks' not in cw_member.keys() else len(cw_member['attacks'])
            if cw_member_attacks < 2:
                if len(tg_users_linked_to_coc_account.get(cw_member['tag']) or []) > 0:
                    for tg_user in tg_users_linked_to_coc_account[cw_member['tag']]:
                        users_whose_coc_accounts_are_mentioned[tg_user].append(
                            {'first_name': tg_users[tg_user]['first_name'],
                             'last_name': tg_users[tg_user]['last_name'],
                             'name': cw_member['name'],
                             'attacks': cw_member_attacks,
                             'attacks_limit': 2})
                else:
                    unlinked_coc_accounts.append({'name': cw_member['name'],
                                                  'attacks': cw_member_attacks,
                                                  'attacks_limit': 2})

        for tg_user, coc_accounts in sorted(users_whose_coc_accounts_are_mentioned.items(),
                                            key=lambda item: sum([coc_account['attacks_limit'] - coc_account['attacks']
                                                                  for coc_account in item[1]]), reverse=True):
            if len(coc_accounts) > 0:
                if ping:
                    answer += f'<a href="tg://user?id={tg_user}">{dm.get_full_name(tg_user)}</a> — '
                else:
                    answer += f'{dm.get_full_name(tg_user)} — '
                answer += ', '.join([f'{dm.of.to_html(coc_account['name'])}: '
                                     f'{coc_account['attacks']} / {coc_account['attacks_limit']}'
                                     for coc_account in coc_accounts])
                answer += '\n'
        answer += '\n'
        for coc_account in unlinked_coc_accounts:
            answer += (f'{dm.of.to_html(coc_account['name'])}: '
                       f'{coc_account['attacks']} / {coc_account['attacks_limit']}\n')
        if (len([coc_accounts
                 for tg_user, coc_accounts
                 in users_whose_coc_accounts_are_mentioned.items()
                 if len(coc_accounts) > 0]
                ) == 0
                and
                len(unlinked_coc_accounts) == 0):
            answer += f'Список пуст'
    else:
        answer += f'В данный момент КВ не идёт\n'
    return answer, ParseMode.HTML, None


@router.message(Command('cw_skips'))
async def command_cw_skips(message: Message, dm: DatabaseManager) -> None:
    answer, parse_mode, reply_markup = await cw_skips(dm, ping=False)
    await message.reply(text=answer, parse_mode=parse_mode, reply_markup=reply_markup)


@router.message(Command('cw_ping'))
async def command_cw_ping(message: Message, dm: DatabaseManager) -> None:
    user_can_ping = await dm.is_admin(message.from_user.id)
    if not user_can_ping:
        await message.reply(text=f'Эту команду могут использовать только соруководители и глава!')
    else:
        answer, parse_mode, reply_markup = await cw_skips(dm, ping=True)
        await message.reply(text=answer, parse_mode=parse_mode, reply_markup=reply_markup)
