from typing import Optional

from aiogram import Router
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.filters.callback_data import CallbackData
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton, InlineKeyboardMarkup
from magic_filter import F

from database_manager import DatabaseManager
from output_formatter.output_formatter import Event

router = Router()


class CWLCallbackFactory(CallbackData, prefix='cwl'):
    state: str
    cwl_round: Optional[int] = None
    cwl_season: Optional[str] = None


async def cwl_rounds_message(dm: DatabaseManager, season: str, command: str):
    if command == 'info':
        answer = (f'<b>📃 Информация о ЛВК</b>\n'
                  f'\n'
                  f'Сезон ЛВК: {dm.of.season(season)}\n'
                  f'\n'
                  f'Выберите день:\n')
    else:
        assert command == 'attacks'
        answer = (f'<b>🗡️ Атаки в ЛВК</b>\n'
                  f'\n'
                  f'Сезон ЛВК: {dm.of.season(season)}\n'
                  f'\n'
                  f'Выберите день:\n')
    cwl_rounds = await dm.get_clan_war_league_clan_own_war_list(season=season, only_last=False)
    cwl_round_title_list = []
    for cwl_round in cwl_rounds:
        cwl_clan, cwl_opponent = cwl_round['clan'], cwl_round['opponent']
        if cwl_round['state'] == 'notInWar':
            cwl_round_title_list.append('')
        elif cwl_round['state'] == 'warEnded':
            if (cwl_clan['stars'], cwl_clan['destructionPercentage']) > (
                    cwl_opponent['stars'], cwl_opponent['destructionPercentage']):
                cwl_round_title_list.append('✅ ')
            elif (cwl_clan['stars'], cwl_clan['destructionPercentage']) < (
                    cwl_opponent['stars'], cwl_opponent['destructionPercentage']):
                cwl_round_title_list.append('❌ ')
            else:
                cwl_round_title_list.append('🟰 ')
        elif cwl_round['state'] == 'inWar':
            cwl_round_title_list.append('🗡 ')
        elif cwl_round['state'] == 'preparation':
            cwl_round_title_list.append('⚙️ ')
        else:
            cwl_round_title_list.append('❓ ')
        cwl_round_title_list[-1] += f'{cwl_clan['name']} vs {cwl_opponent['name']}'
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=cwl_round_title_list[i],
            callback_data=CWLCallbackFactory(
                state='cwl_' + command,
                cwl_round=i
            ).pack()
        )]
        for i in range(len(cwl_rounds))
    ])
    return answer, ParseMode.HTML, keyboard


async def cwl_info(dm: DatabaseManager, round_number: Optional[int] = None):
    if round_number is None:
        cwl_round_number, cwl = await dm.get_clan_war_league_clan_own_war_list(
            season=await dm.clan_war_league_season(only_last=True),
            only_last=True
        )
    else:
        cwl_round_number, cwl = round_number, (await dm.get_clan_war_league_clan_own_war_list(
            season=await dm.clan_war_league_season(only_last=True),
            only_last=False
        ))[round_number]
    cwl_season = await dm.clan_war_league_season(only_last=True)
    answer = (f'<b>📃 Информация о ЛВК</b>\n'
              f'\n'
              f'Сезон ЛВК: {dm.of.season(cwl_season)}\n'
              f'День {cwl_round_number + 1}\n'
              f'\n')
    if cwl['state'] == 'preparation':
        answer += (f'{dm.of.to_html(cwl['clan']['name'])} vs {dm.of.to_html(cwl['opponent']['name'])}\n'
                   f'{cwl['teamSize']} 👤 vs {cwl['teamSize']} 👤\n'
                   f'\n'
                   f'{dm.of.event_datetime(Event.CWLW, cwl['startTime'], cwl['endTime'], True)}')
    elif cwl['state'] == 'inWar':
        answer += (f'{dm.of.to_html(cwl['clan']['name'])} vs {dm.of.to_html(cwl['opponent']['name'])}\n'
                   f'{cwl['teamSize']} 👤 vs {cwl['teamSize']} 👤\n'
                   f'{cwl['clan']['attacks']} 🗡 vs {cwl['opponent']['attacks']} 🗡\n'
                   f'{cwl['clan']['stars']} ⭐ vs {cwl['opponent']['stars']} ⭐\n'
                   f'{format(cwl['clan']['destructionPercentage'], '.2f')}% vs '
                   f'{format(cwl['opponent']['destructionPercentage'], '.2f')}%\n'
                   f'\n'
                   f'{dm.of.event_datetime(Event.CWLW, cwl['startTime'], cwl['endTime'], True)}')
    elif cwl['state'] == 'warEnded':
        answer += (f'{dm.of.to_html(cwl['clan']['name'])} vs {dm.of.to_html(cwl['opponent']['name'])}\n'
                   f'{cwl['teamSize']} 👤 vs {cwl['teamSize']} 👤\n'
                   f'{cwl['clan']['attacks']} 🗡 vs {cwl['opponent']['attacks']} 🗡\n'
                   f'{cwl['clan']['stars']} ⭐ vs {cwl['opponent']['stars']} ⭐\n'
                   f'{format(cwl['clan']['destructionPercentage'], '.2f')}% vs '
                   f'{format(cwl['opponent']['destructionPercentage'], '.2f')}%\n'
                   f'\n'
                   f'{dm.of.event_datetime(Event.CWLW, cwl['startTime'], cwl['endTime'], True)}\n'
                   f'\n')
        if (cwl['clan']['stars'], cwl['clan']['destructionPercentage']) > (
                cwl['opponent']['stars'], cwl['opponent']['destructionPercentage']):
            answer += f'🎉 Победа!'
        elif (cwl['clan']['stars'], cwl['clan']['destructionPercentage']) < (
                cwl['opponent']['stars'], cwl['opponent']['destructionPercentage']):
            answer += f'😢 Поражение'
        else:
            answer += f'⚖️ Ничья'
    else:
        answer += f'В данный момент война не идёт\n'
    previous_cwl_round_button = InlineKeyboardButton(
        text='⬅️',
        callback_data=CWLCallbackFactory(
            state='cwl_info',
            cwl_round=cwl_round_number - 1
        ).pack())
    next_cwl_round_button = InlineKeyboardButton(
        text='➡️',
        callback_data=CWLCallbackFactory(
            state='cwl_info',
            cwl_round=cwl_round_number + 1
        ).pack())
    all_cwl_rounds_button = InlineKeyboardButton(
        text='🧾 Все дни',
        callback_data=CWLCallbackFactory(
            state='cwl_info_rounds',
            cwl_season=cwl_season
        ).pack())
    inline_keyboard_row = []
    if cwl_round_number > 0:
        inline_keyboard_row.append(previous_cwl_round_button)
    if cwl_round_number < await dm.get_cwl_round_amount(cwl_season) - 1:
        inline_keyboard_row.append(next_cwl_round_button)
    inline_keyboard_row.append(all_cwl_rounds_button)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[inline_keyboard_row])
    return answer, ParseMode.HTML, keyboard


@router.message(Command('cwl_info'))
async def command_cwl_info(message: Message, dm: DatabaseManager):
    text, parse_mode, reply_markup = await cwl_info(dm)
    reply_from_bot = await message.reply(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
    await dm.register_message(reply_from_bot.chat.id, reply_from_bot.message_id, message.from_user.id)


@router.callback_query(CWLCallbackFactory.filter(F.state == 'cwl_info'))
async def callback_cwl_info(callback: CallbackQuery, callback_data: CWLCallbackFactory,
                            dm: DatabaseManager) -> None:
    user_is_message_owner = await dm.check_message(callback.message.chat.id,
                                                   callback.message.message_id,
                                                   callback.from_user.id)
    if not user_is_message_owner:
        await callback.answer('Эта кнопка не для вас!')
    else:
        text, parse_mode, reply_markup = await cwl_info(dm, callback_data.cwl_round)
        await callback.message.edit_text(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
        await callback.answer()


@router.callback_query(CWLCallbackFactory.filter(F.state == 'cwl_info_rounds'))
async def callback_cwl_info_rounds(callback: CallbackQuery, callback_data: CWLCallbackFactory,
                                   dm: DatabaseManager) -> None:
    user_is_message_owner = await dm.check_message(callback.message.chat.id,
                                                   callback.message.message_id,
                                                   callback.from_user.id)
    if not user_is_message_owner:
        await callback.answer('Эта кнопка не для вас!')
    else:
        text, parse_mode, reply_markup = await cwl_rounds_message(dm, callback_data.cwl_season, 'info')
        await callback.message.edit_text(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
        await callback.answer()


async def cwl_attacks(dm: DatabaseManager, round_number: Optional[int] = None):
    if round_number is None:
        cwl_round_number, cwl = await dm.get_clan_war_league_clan_own_war_list(
            season=await dm.clan_war_league_season(only_last=True),
            only_last=True
        )
    else:
        cwl_round_number, cwl = round_number, (await dm.get_clan_war_league_clan_own_war_list(
            season=await dm.clan_war_league_season(only_last=True),
            only_last=False
        ))[round_number]
    cwl_season = await dm.clan_war_league_season(only_last=True)
    answer = (f'<b>🗡️ Атаки в ЛВК</b>\n'
              f'\n'
              f'Сезон ЛВК: {dm.of.season(cwl_season)}\n'
              f'День {cwl_round_number + 1}\n'
              f'\n')
    if cwl['state'] in ['preparation']:
        answer += f'{cwl['clan']['name']} vs {cwl['opponent']['name']}\n'
        answer += (f'{dm.of.event_datetime(Event.CWLW, cwl['startTime'], cwl['endTime'], True)}\n'
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
        clan_position = dm.get_map_positions(cwl['clan']['members'])
        output_strings = [''] * len(clan_position)
        for member in cwl['clan']['members']:
            output_strings[clan_position[member['tag']] - 1] = \
                f'{clan_position[member['tag']]}) {desc.get(member['tag']) or dm.of.to_html(member['name'])}'
        answer += '\n'.join(output_strings)
    elif cwl['state'] in ['inWar', 'warEnded']:
        answer += f'{cwl['clan']['name']} vs {cwl['opponent']['name']}\n'
        answer += f'{dm.of.event_datetime(Event.CWLW, cwl['startTime'], cwl['endTime'], True)}\n\n'
        clan_position = dm.get_map_positions(cwl['clan']['members'])
        opponent_position = dm.get_map_positions(cwl['opponent']['members'])
        output_strings = [''] * len(clan_position)
        for member in cwl['clan']['members']:
            attacks_count = 0
            if 'attacks' in member.keys():
                attacks_count += len(member['attacks'])
            output_strings[clan_position[member['tag']] - 1] += \
                f'{clan_position[member['tag']]}) {dm.of.to_html(member['name'])} — {attacks_count} / 1\n'
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
        answer += f'В данный момент ЛВК не идёт\n'
    previous_cwl_round_button = InlineKeyboardButton(
        text='⬅️',
        callback_data=CWLCallbackFactory(
            state='cwl_attacks',
            cwl_round=cwl_round_number - 1
        ).pack())
    next_cwl_round_button = InlineKeyboardButton(
        text='➡️',
        callback_data=CWLCallbackFactory(
            state='cwl_attacks',
            cwl_round=cwl_round_number + 1
        ).pack())
    all_cwl_rounds_button = InlineKeyboardButton(
        text='🧾 Все дни',
        callback_data=CWLCallbackFactory(
            state='cwl_attacks_rounds',
            cwl_season=cwl_season
        ).pack())
    inline_keyboard_row = []
    if cwl_round_number > 0:
        inline_keyboard_row.append(previous_cwl_round_button)
    if cwl_round_number < await dm.get_cwl_round_amount(cwl_season) - 1:
        inline_keyboard_row.append(next_cwl_round_button)
    inline_keyboard_row.append(all_cwl_rounds_button)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[inline_keyboard_row])
    return answer, ParseMode.HTML, keyboard


@router.message(Command('cwl_attacks'))
async def command_cwl_attacks(message: Message, dm: DatabaseManager) -> None:
    answer, parse_mode, reply_markup = await cwl_attacks(dm)
    reply_from_bot = await message.reply(text=answer, parse_mode=parse_mode, reply_markup=reply_markup)
    await dm.register_message(reply_from_bot.chat.id, reply_from_bot.message_id, message.from_user.id)


@router.callback_query(CWLCallbackFactory.filter(F.state == 'cwl_attacks'))
async def callback_cwl_attacks(callback: CallbackQuery, callback_data: CWLCallbackFactory,
                               dm: DatabaseManager) -> None:
    user_is_message_owner = await dm.check_message(callback.message.chat.id,
                                                   callback.message.message_id,
                                                   callback.from_user.id)
    if not user_is_message_owner:
        await callback.answer('Эта кнопка не для вас!')
    else:
        text, parse_mode, reply_markup = await cwl_attacks(dm, callback_data.cwl_round)
        await callback.message.edit_text(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
        await callback.answer()


@router.callback_query(CWLCallbackFactory.filter(F.state == 'cwl_attacks_rounds'))
async def callback_cwl_attacks_rounds(callback: CallbackQuery, callback_data: CWLCallbackFactory,
                                      dm: DatabaseManager) -> None:
    user_is_message_owner = await dm.check_message(callback.message.chat.id,
                                                   callback.message.message_id,
                                                   callback.from_user.id)
    if not user_is_message_owner:
        await callback.answer('Эта кнопка не для вас!')
    else:
        text, parse_mode, reply_markup = await cwl_rounds_message(dm, callback_data.cwl_season, 'attacks')
        await callback.message.edit_text(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
        await callback.answer()


async def cwl_skips(dm: DatabaseManager, ping: bool):
    round_number, cwl = await dm.get_clan_war_league_clan_own_war_list(
        season=await dm.clan_war_league_season(only_last=True),
        only_last=True
    )
    cwl_season = await dm.clan_war_league_season(only_last=True)
    answer = (f'<b>🙈 Список не проатаковавших в ЛВК</b>\n'
              f'\n'
              f'Сезон ЛВК: {dm.of.season(cwl_season)}\n'
              f'\n')
    if cwl['state'] in ['inWar', 'warEnded']:
        answer += (f'❗ {dm.of.event_datetime(Event.CWLW, cwl['startTime'], cwl['endTime'], False)}\n'
                   f'\n')
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
        for cwl_member in cwl['clan']['members']:
            cwl_member_attacks = 0 if 'attacks' not in cwl_member.keys() else len(cwl_member['attacks'])
            if cwl_member_attacks < 1:
                if len(tg_users_linked_to_coc_account.get(cwl_member['tag']) or []) > 0:
                    for tg_user in tg_users_linked_to_coc_account[cwl_member['tag']]:
                        users_whose_coc_accounts_are_mentioned[tg_user].append(
                            {'first_name': tg_users[tg_user]['first_name'],
                             'last_name': tg_users[tg_user]['last_name'],
                             'name': cwl_member['name'],
                             'attacks': cwl_member_attacks,
                             'attacks_limit': 1})
                else:
                    unlinked_coc_accounts.append({'name': cwl_member['name'],
                                                  'attacks': cwl_member_attacks,
                                                  'attacks_limit': 1})

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
                       f'{coc_account['attacks']} / {coc_account['attacks_limit']}'
                       f'\n')
        if (len([coc_accounts
                 for tg_user, coc_accounts
                 in users_whose_coc_accounts_are_mentioned.items()
                 if len(coc_accounts) > 0]
                ) == 0
                and
                len(unlinked_coc_accounts) == 0):
            answer += f'Список пуст'
    else:
        answer += f'В данный момент ЛВК не идёт\n'
    return answer, ParseMode.HTML, None


@router.message(Command('cwl_skips'))
async def command_cwl_skips(message: Message, dm: DatabaseManager) -> None:
    answer, parse_mode, reply_markup = await cwl_skips(dm, ping=False)
    await message.reply(text=answer, parse_mode=parse_mode, reply_markup=reply_markup)


@router.message(Command('cwl_ping'))
async def command_cwl_ping(message: Message, dm: DatabaseManager) -> None:
    user_can_ping = await dm.is_admin(message.from_user.id)
    if not user_can_ping:
        await message.reply(text=f'Эту команду могут использовать только соруководители и глава!')
    else:
        answer, parse_mode, reply_markup = await cwl_skips(dm, ping=True)
        await message.reply(text=answer, parse_mode=parse_mode, reply_markup=reply_markup)


async def cwl_map(dm: DatabaseManager, collapsed: bool):
    cwl = await dm.get_clan_war_league(clan_war_league_season=await dm.clan_war_league_season(only_last=True))
    answer = (f'<b>🗺️ Карта ЛВК</b>\n'
              f'\n'
              f'Сезон ЛВК: {dm.of.season(cwl['season'])}\n'
              f'\n')
    _, first_cwl_war = await dm.get_clan_war_league_clan_own_war_list(
        season=await dm.clan_war_league_season(only_last=True),
        only_last=True
    )
    cwl_size = len(first_cwl_war['clan']['members'])
    clans = []
    for cwl_participating_clan in cwl['clans']:
        clan_answer = ''
        clan_answer += f'<b>{cwl_participating_clan['name']}</b>\n'
        town_hall_levels = []
        for cwl_clan_member in cwl_participating_clan['members']:
            town_hall_levels.append(cwl_clan_member['townHallLevel'])
        town_hall_levels.sort(reverse=True)
        if not collapsed:
            clan_answer += 'Список ТХ: ' + ', '.join(map(str, town_hall_levels))
            clan_answer += ('\n'
                            '\n')
            clan_answer += f'Средний ТХ: {round(sum(town_hall_levels) / len(town_hall_levels), 2)}\n\n'
        top = town_hall_levels[:cwl_size]
        clan_answer += f'Средний ТХ (среди топ-{cwl_size}): {round(sum(top) / len(top), 2)}\n'
        clans.append((clan_answer, round(sum(top) / len(top), 2)))
    clans.sort(key=lambda x: x[1], reverse=True)
    answer += '\n'.join([c[0] for c in clans])
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='⬇️ Развернуть' if collapsed else '⬆️ Свернуть',
                              callback_data=CWLCallbackFactory(
                                  state='cwl_map_expanded' if collapsed else 'cwl_map_collapsed'
                              ).pack())]
    ])
    return answer, ParseMode.HTML, keyboard


@router.message(Command('cwl_map'))
async def command_cwl_map(message: Message, dm: DatabaseManager):
    text, parse_mode, reply_markup = await cwl_map(dm, True)
    reply_from_bot = await message.reply(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
    await dm.register_message(reply_from_bot.chat.id, reply_from_bot.message_id, message.from_user.id)


@router.callback_query(CWLCallbackFactory.filter(F.state == 'cwl_map_expanded'))
async def callback_cwl_map_expanded(callback: CallbackQuery, callback_data: CWLCallbackFactory,
                                    dm: DatabaseManager) -> None:
    user_is_message_owner = await dm.check_message(callback.message.chat.id,
                                                   callback.message.message_id,
                                                   callback.from_user.id)
    if not user_is_message_owner:
        await callback.answer('Эта кнопка не для вас!')
    else:
        text, parse_mode, reply_markup = await cwl_map(dm, False)
        await callback.message.edit_text(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
        await callback.answer()


@router.callback_query(CWLCallbackFactory.filter(F.state == 'cwl_map_collapsed'))
async def callback_cwl_map_collapsed(callback: CallbackQuery, callback_data: CWLCallbackFactory,
                                     dm: DatabaseManager) -> None:
    user_is_message_owner = await dm.check_message(callback.message.chat.id,
                                                   callback.message.message_id,
                                                   callback.from_user.id)
    if not user_is_message_owner:
        await callback.answer('Эта кнопка не для вас!')
    else:
        text, parse_mode, reply_markup = await cwl_map(dm, True)
        await callback.message.edit_text(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
        await callback.answer()
