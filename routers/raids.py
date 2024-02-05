from aiogram import Router
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import Message

from database_manager import DatabaseManager
from output_formatter.output_formatter import Event

router = Router()


async def raids_info(dm: DatabaseManager):
    answer = (f'<b>📃 Информация о рейдах</b>\n'
              f'\n')
    raids = await dm.get_raid_weekend(raid_weekend_start_time=await dm.raid_weekend_start_time(only_last=True))
    districts_count = 9
    answer += f'{dm.of.event_datetime(Event.RW, raids['startTime'], raids['endTime'], True)}\n\n'
    answer += f'Получено столичного золота: {raids["capitalTotalLoot"]} 🟡\n'
    raids_completed = raids["enemyDistrictsDestroyed"] // districts_count
    answer += f'Завершено рейдов: {raids_completed} ⚔️\n'
    answer += f'Разрушено деревень: {raids["enemyDistrictsDestroyed"]} 🛖\n'
    answer += f'Сделано атак: {raids["totalAttacks"]} 🗡️\n'
    return answer, ParseMode.HTML, None


@router.message(Command('raids_info'))
async def command_raids_info(message: Message, dm: DatabaseManager) -> None:
    answer, parse_mode, keyboard = await raids_info(dm)
    await message.reply(text=answer, parse_mode=parse_mode, keyboard=keyboard)


async def raids_loot(dm: DatabaseManager):
    answer = ('<b>🟡 Полученное золото в рейдах</b>\n'
              '\n')
    raids = await dm.get_raid_weekend(raid_weekend_start_time=await dm.raid_weekend_start_time(only_last=True))
    answer += f'{dm.of.event_datetime(Event.RW, raids['startTime'], raids['endTime'], True)}\n\n'

    query = await dm.req_connection.fetch('''
        SELECT tag
        FROM public.clash_of_clans_account
        WHERE in_clan --AND first_seen < $1
    ''')  # , datetime.strptime(raids['endTime'], '%Y%m%dT%H%M%S.%fZ')
    raids_data = {raids_member['tag']: {'name': raids_member['name'],
                                        'capital_resources_looted': raids_member['capitalResourcesLooted'],
                                        'attacks': raids_member['attacks'],
                                        'attack_limit_sum':
                                            raids_member['attackLimit'] + raids_member['bonusAttackLimit']}
                  for raids_member in raids['members']}
    answer_list = []
    for tag in set(list(raids_data.keys()) + [record['tag'] for record in query]):
        answer_list.append(
            {'name': (dm.get_name(tag)) or raids_data[tag]['name'],
             'capital_resources_looted': raids_data[tag]['capital_resources_looted'] if raids_data.get(tag) else 0,
             'attacks': raids_data[tag]['attacks'] if raids_data.get(tag) else 0,
             'attack_limit_sum': (raids_data[tag]['attack_limit_sum']) if raids_data.get(tag) else 6
             })
    answer_list.sort(key=lambda elem: (-elem['capital_resources_looted'], elem['name']))
    for i, record in enumerate(answer_list):
        answer += (f'{i + 1}) {dm.of.to_html(record['name'])} — {record['capital_resources_looted']} 🟡 '
                   f'({record['attacks']} / {record['attack_limit_sum']})\n')
    if len(answer_list) == 0:
        answer += f'Список пуст'
    return answer, ParseMode.HTML, None


@router.message(Command('raids_loot'))
async def command_raids_loot(message: Message, dm: DatabaseManager) -> None:
    answer, parse_mode, keyboard = await raids_loot(dm)
    await message.reply(text=answer, parse_mode=parse_mode, keyboard=keyboard)


async def raids_skips(dm: DatabaseManager, ping: bool):
    raids = await dm.get_raid_weekend(raid_weekend_start_time=await dm.raid_weekend_start_time(only_last=True))
    answer = (f'<b>🙈 Список не проатаковавших в рейдах</b>\n'
              f'\n')
    answer += f'{dm.of.event_datetime(Event.RW, raids['startTime'], raids['endTime'], True)}\n\n'
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

    raids_member_info = {raids_member['tag']: {'attacks': raids_member['attacks'],
                                               'attack_limit': raids_member['attackLimit'],
                                               'bonus_attack_limit': raids_member['bonusAttackLimit']}
                         for raids_member in raids['members']}
    query = await dm.req_connection.fetch('''
        SELECT tag, name
        FROM public.clash_of_clans_account
        WHERE in_clan --AND first_seen < $1
    ''')  # , datetime.strptime(raids['endTime'], '%Y%m%dT%H%M%S.%fZ')
    raid_potential_members = [{'tag': tag,
                               'name': dm.get_name(tag),
                               'attacks': raids_member_info[tag]['attacks']
                               if raids_member_info.get(tag) else 0,
                               'attack_limit': raids_member_info[tag]['attack_limit']
                               if raids_member_info.get(tag) else 5,
                               'bonus_attack_limit': raids_member_info[tag]['bonus_attack_limit']
                               if raids_member_info.get(tag) else 1}
                              for tag in [record['tag'] for record in query]]
    for raid_potential_member in raid_potential_members:
        if raid_potential_member['attacks'] < 6:
            if len(tg_users_linked_to_coc_account.get(raid_potential_member['tag']) or []) > 0:
                for tg_user in tg_users_linked_to_coc_account[raid_potential_member['tag']]:
                    (users_whose_coc_accounts_are_mentioned[tg_user].
                     append({'first_name': tg_users[tg_user]['first_name'],
                             'last_name': tg_users[tg_user]['last_name'],
                             'name': raid_potential_member['name'],
                             'attacks': raid_potential_member['attacks'],
                             'attacks_limit':
                                 raid_potential_member['attack_limit'] + raid_potential_member['bonus_attack_limit']}))
            else:
                (unlinked_coc_accounts
                 .append({'name': raid_potential_member['name'],
                          'attacks': raid_potential_member['attacks'],
                          'attacks_limit':
                              raid_potential_member['attack_limit'] + raid_potential_member['bonus_attack_limit']}))

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
        answer += f'{dm.of.to_html(coc_account['name'])}: {coc_account['attacks']} / {coc_account['attacks_limit']}\n'
    if len(users_whose_coc_accounts_are_mentioned) == 0 and len(unlinked_coc_accounts) == 0:
        answer += f'Список пуст'
    return answer, ParseMode.HTML, None


async def raids_analysis(dm: DatabaseManager):
    raids = await dm.get_raid_weekend(raid_weekend_start_time=await dm.raid_weekend_start_time(only_last=True))
    answer = (f'<b>📊 Анализ атак в рейдах</b>\n'
              f'\n')
    answer += f'{dm.of.event_datetime(Event.RW, raids['startTime'], raids['endTime'], True)}\n\n'
    clan_districts_attacks = {}
    for attack_log in raids['attackLog']:
        for district in attack_log['districts']:
            if district['destructionPercent'] != 100:
                continue
            attack_count = district['attackCount']
            if attack_count > 1:
                average_destruction = district['attacks'][1]['destructionPercent'] / (attack_count - 1)
            else:
                average_destruction = 100.0
            if district['name'] not in clan_districts_attacks.keys():
                clan_districts_attacks[district['name']] = [(attack_count, average_destruction, district)]
            else:
                clan_districts_attacks[district['name']].append((attack_count, average_destruction, district))

    for k, v in clan_districts_attacks.items():
        answer += f'\n<b>{dm.of.district(k)}</b>\n'
        best_district = sorted(v, key=lambda x: (x[0], -x[1]))[0][2]
        answer += f'👍 Лучшее разрушение (кол-во атак: {len(best_district['attacks'])}):\n'
        for attack in best_district['attacks'][::-1]:
            if attack['stars'] == 0:
                answer += (f'{dm.of.to_html(attack["attacker"]["name"])} — '
                           f'{attack["destructionPercent"]}%\n')
            else:
                answer += (f'{dm.of.to_html(attack["attacker"]["name"])} — '
                           f'{"⭐" * attack["stars"]} ({attack["destructionPercent"]}%)\n')
        worst_district = sorted(v, key=lambda x: (x[0], -x[1]))[-1][2]
        answer += f'👎 Худшее разрушение (кол-во атак: {len(worst_district['attacks'])}):\n'
        for attack in worst_district['attacks'][::-1]:
            if attack['stars'] == 0:
                answer += (f'{dm.of.to_html(attack["attacker"]["name"])} — '
                           f'{attack["destructionPercent"]}%\n')
            else:
                answer += (f'{dm.of.to_html(attack["attacker"]["name"])} — '
                           f'{"⭐" * attack["stars"]} ({attack["destructionPercent"]}%)\n')
    if len(clan_districts_attacks) == 0:
        answer += f'Список пуст'
    return answer, ParseMode.HTML, None


@router.message(Command('raids_skips'))
async def command_raids_skips(message: Message, dm: DatabaseManager) -> None:
    answer, parse_mode, keyboard = await raids_skips(dm, ping=False)
    await message.reply(text=answer, parse_mode=parse_mode, keyboard=keyboard)


@router.message(Command('raids_ping'))
async def command_raids_ping(message: Message, dm: DatabaseManager) -> None:
    user_is_admin = await dm.is_admin(message.from_user.id)
    if not user_is_admin:
        await message.reply(text=f'Эту команду могут использовать только соруководители и глава')
    else:
        answer, parse_mode, keyboard = await raids_skips(dm, ping=True)
        await message.reply(text=answer, parse_mode=parse_mode, keyboard=keyboard)


@router.message(Command('raids_analysis'))
async def command_raids_analysis(message: Message, dm: DatabaseManager) -> None:
    answer, parse_mode, keyboard = await raids_analysis(dm)
    await message.reply(text=answer, parse_mode=parse_mode, keyboard=keyboard)
