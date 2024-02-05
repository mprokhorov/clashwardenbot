from aiogram import Router, Bot
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.filters.callback_data import CallbackData
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton, InlineKeyboardMarkup
from magic_filter import F

from bot.filters import NewChatMembersFilter
from database_manager import DatabaseManager

router = Router()


class MembersCallbackFactory(CallbackData, prefix='members'):
    state: str


async def members(dm: DatabaseManager):
    query = await dm.req_connection.fetch('''
        SELECT name, town_hall, barbarian_king, archer_queen, grand_warden, royal_champion
        FROM public.clash_of_clans_account
        WHERE in_clan
        ORDER BY town_hall DESC, (barbarian_king + archer_queen + grand_warden + royal_champion) DESC
    ''')
    answer = (f'<b>👥 Участники клана</b>\n'
              f'\n')
    for i, record in enumerate(query):
        answer += (f'{i + 1}) {dm.of.to_html(record['name'])} — 🛖 {record['town_hall']}, '
                   f'👑 {record['barbarian_king']} / {record['archer_queen']} / '
                   f'{record['grand_warden']} / {record['royal_champion']}\n')
    if len(query) == 0:
        answer += f'Список пуст'
    return answer, ParseMode.HTML, None


@router.message(Command('members'))
async def cmd_members(message: Message, dm: DatabaseManager):
    answer, parse_mode, reply_markup = await members(dm)
    await message.reply(text=answer, parse_mode=parse_mode, reply_markup=reply_markup)


async def donations_expanded(dm: DatabaseManager):
    query = await dm.req_connection.fetch('''
        SELECT name, role, donations_given FROM
            (SELECT name, role, donations_given
            FROM public.clash_of_clans_account
            WHERE in_clan AND role NOT IN ('coLeader', 'leader')
            ORDER BY donations_given DESC
            LIMIT 10) t
            UNION
            (SELECT name, role, donations_given
            FROM public.clash_of_clans_account
            WHERE in_clan AND role IN ('coLeader', 'leader')
            ORDER BY donations_given DESC
            LIMIT 10)
        ORDER BY donations_given DESC
    ''')
    answer = (f'<b>🥇 Лучшие жертвователи</b>\n'
              f'\n'
              f'В список включены лучшие 10 аккаунтов среди участников и старейшин и '
              f'лучшие 10 аккаунтов среди соруководителей и главы\n'
              f'\n')
    for i, record in enumerate(query):
        answer += (f'{i + 1}) {dm.of.to_html(record['name'])}, {dm.of.role(record['role'])} — '
                   f'🪖 {record['donations_given']}\n')

    query = await dm.req_connection.fetch('''
        SELECT name, donations_given
        FROM public.clash_of_clans_account
        WHERE in_clan AND role = 'admin' AND tag NOT IN
            (SELECT tag
            FROM public.clash_of_clans_account
            WHERE in_clan AND role NOT IN ('coLeader', 'leader')
            ORDER BY donations_given DESC
            LIMIT 10)
        ORDER BY donations_given, name
    ''')
    answer += (f'\n'
               f'Кандидаты на понижение до участника: ' + ', '.
               join(f'{dm.of.to_html(record['name'])} — 🪖 {record['donations_given']}'
                    for record in query)) if len(query) != 0 else ''

    query = await dm.req_connection.fetch('''
        SELECT name, donations_given
        FROM public.clash_of_clans_account
        WHERE in_clan AND role = 'member' AND tag IN
            (SELECT tag
            FROM public.clash_of_clans_account
            WHERE in_clan AND role NOT IN ('coLeader', 'leader')
            ORDER BY donations_given DESC
            LIMIT 10)
        ORDER BY donations_given, name
    ''')
    answer += (f'\n'
               f'\n'
               f'Кандидаты на повышение до старейшины: ' + ', '.
               join(f'{dm.of.to_html(record['name'])} — 🪖 {record['donations_given']}'
                    for record in query)) if len(query) != 0 else ''

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='⬆️ Свернуть',
                              callback_data=MembersCallbackFactory(
                                  state='donations_collapsed'
                              ).pack())]
    ])
    return answer, ParseMode.HTML, keyboard


async def donations_collapsed(dm: DatabaseManager):
    query = await dm.req_connection.fetch('''
        SELECT name, role, donations_given
        FROM public.clash_of_clans_account
        WHERE in_clan AND role NOT IN ('coLeader', 'leader')
        ORDER BY donations_given DESC
        LIMIT 10
    ''')
    answer = (f'<b>🥇 Лучшие жертвователи</b>\n'
              f'\n'
              f'В список включены лучшие 10 аккаунтов среди участников и старейшин\n'
              f'\n')
    for i, record in enumerate(query):
        answer += (f'{i + 1}) {dm.of.to_html(record['name'])}, {dm.of.role(record['role'])} — '
                   f'🪖 {record['donations_given']}\n')

    query = await dm.req_connection.fetch('''
        SELECT name, donations_given
        FROM public.clash_of_clans_account
        WHERE in_clan AND role = 'admin' AND tag NOT IN
            (SELECT tag
            FROM public.clash_of_clans_account
            WHERE in_clan AND role NOT IN ('coLeader', 'leader')
            ORDER BY donations_given DESC
            LIMIT 10)
        ORDER BY donations_given, name
    ''')
    answer += (f'\n'
               f'Кандидаты на понижение до участника: ' + ', '.
               join(f'{dm.of.to_html(record['name'])} — 🪖 {record['donations_given']}'
                    for record in query)) if len(query) != 0 else ''

    query = await dm.req_connection.fetch('''
        SELECT name, donations_given
        FROM public.clash_of_clans_account
        WHERE in_clan AND role = 'member' AND tag IN
            (SELECT tag
            FROM public.clash_of_clans_account
            WHERE in_clan AND role NOT IN ('coLeader', 'leader')
            ORDER BY donations_given DESC
            LIMIT 10)
        ORDER BY donations_given, name
    ''')
    answer += (f'\n'
               f'\n'
               f'Кандидаты на повышение до старейшины: ' + ', '.
               join(f'{dm.of.to_html(record['name'])} — 🪖 {record['donations_given']}'
                    for record in query)) if len(query) != 0 else ''

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='⬇️ Развернуть',
                              callback_data=MembersCallbackFactory(
                                  state='donations_expanded'
                              ).pack())]
    ])
    return answer, ParseMode.HTML, keyboard


@router.message(Command('donations'))
async def cmd_donations(message: Message, dm: DatabaseManager):
    answer, parse_mode, reply_markup = await donations_expanded(dm)
    reply_from_bot = await message.reply(text=answer, parse_mode=parse_mode, reply_markup=reply_markup)
    await dm.register_message(reply_from_bot.chat.id, reply_from_bot.message_id, message.from_user.id)


@router.callback_query(MembersCallbackFactory.filter(F.state == 'donations_collapsed'))
async def callback_donations_collapsed(callback: CallbackQuery, callback_data: MembersCallbackFactory,
                                       dm: DatabaseManager) -> None:
    user_is_message_owner = await dm.check_message(callback.message.chat.id,
                                                   callback.message.message_id,
                                                   callback.from_user.id)
    if not user_is_message_owner:
        await callback.answer('Эта кнопка не для вас!')
    else:
        text, parse_mode, reply_markup = await donations_collapsed(dm)
        await callback.message.edit_text(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
        await callback.answer()


@router.callback_query(MembersCallbackFactory.filter(F.state == 'donations_expanded'))
async def callback_donations_expanded(callback: CallbackQuery, callback_data: MembersCallbackFactory,
                                      dm: DatabaseManager) -> None:
    user_is_message_owner = await dm.check_message(callback.message.chat.id,
                                                   callback.message.message_id,
                                                   callback.from_user.id)
    if not user_is_message_owner:
        await callback.answer('Эта кнопка не для вас!')
    else:
        text, parse_mode, reply_markup = await donations_expanded(dm)
        await callback.message.edit_text(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
        await callback.answer()


async def contributions(dm: DatabaseManager):
    query = await dm.req_connection.fetch('''
        SELECT tag, capital_gold_contributed, contribution_date_and_time
        FROM public.clan_capital_contribution
        ORDER BY contribution_date_and_time DESC
        LIMIT 10
    ''')
    answer = (f'<b>🤝 Вклады в столице</b>\n'
              f'\n')
    for i, record in enumerate(query):
        answer += (f'{dm.of.to_html(dm.get_name(record['tag']))} — {record['capital_gold_contributed']} 🟡 '
                   f'{dm.of.shortest_datetime(record['contribution_date_and_time'])}\n')
    if len(query) == 0:
        answer += f'Список пуст'
    return answer, ParseMode.HTML, None


@router.message(Command('contributions'))
async def cmd_contributions(message: Message, dm: DatabaseManager):
    answer, parse_mode, reply_markup = await contributions(dm)
    reply_from_bot = await message.reply(text=answer, parse_mode=parse_mode, reply_markup=reply_markup)
    await dm.register_message(reply_from_bot.chat.id, reply_from_bot.message_id, message.from_user.id)
