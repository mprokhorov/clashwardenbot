from collections import namedtuple
from typing import Tuple, Optional

from aiogram import Router
from aiogram.enums import ParseMode, ChatType
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup

from database_manager import DatabaseManager
from output_formatter.output_formatter import Event

router = Router()


async def raids_info(dm: DatabaseManager) -> Tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    text = (
        f'<b>⚔️ Информация о рейдах</b>\n'
        f'\n'
    )
    raid = await dm.load_raid_weekend()
    if dm.of.state(raid) in ['ongoing', 'ended']:
        text += dm.of.raid_ongoing_or_ended(raid)
    else:
        text += 'Информация о рейдах отсутствует\n'
    return text, ParseMode.HTML, None


async def raids_attacks(dm: DatabaseManager) -> Tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    text = (
        f'<b>🗡️ Атаки в рейдах</b>\n'
        f'\n'
    )
    raid = await dm.load_raid_weekend()
    if dm.of.state(raid) in ['ongoing', 'ended']:
        RaidMember = namedtuple(
            typename='AllegedRaidMember', field_names='player_tag attacks_spent attacks_limit gold_looted'
        )
        raid_members = []
        for raid_member in raid['members']:
            raid_members.append(
                RaidMember(
                    player_tag=raid_member['tag'],
                    attacks_spent=raid_member['attacks'],
                    attacks_limit=raid_member['attackLimit'] + raid_member['bonusAttackLimit'],
                    gold_looted=raid_member['capitalResourcesLooted'])
            )
        if raid['state'] in ['ended']:
            rows = await dm.acquired_connection.fetch('''
                SELECT player_tag
                FROM player
                WHERE
                    clan_tag = $1
                    AND is_player_in_clan
                    AND (first_seen < $2 OR (SELECT MIN(first_seen) FROM player WHERE clan_tag = $1) > $2)
                    AND NOT (player_tag = any($3::varchar[]))
            ''', dm.clan_tag, dm.of.to_datetime(raid['endTime']), [alleged_raid_member.player_tag
                                                                   for alleged_raid_member in raid_members])
            for row in rows:
                raid_members.append(
                    RaidMember(player_tag=row['player_tag'], attacks_spent=0, attacks_limit=6, gold_looted=0)
                )
        raid_members.sort(key=lambda rm: (-rm.gold_looted, dm.load_name(rm.player_tag)))
        text += (
            f'{dm.of.raid_ongoing_or_ended(raid)}'
            f'\n'
        )
        for i, raid_member in enumerate(raid_members):
            text += (
                f'{i + 1}) {dm.of.to_html(dm.load_name(raid_member.player_tag))}: '
                f'{raid_member.gold_looted} {dm.of.get_capital_gold_emoji()} '
                f'({raid_member.attacks_spent} / {raid_member.attacks_limit})\n'
            )
        if len(raid_members) == 0:
            text += f'Список пуст\n'
    else:
        text += 'Информация о рейдах отсутствует\n'
    return text, ParseMode.HTML, None


async def raids_skips_raids_ping(
        dm: DatabaseManager, message: Message, ping: bool
) -> Tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    if ping:
        text = (
            f'<b>🔔 Напоминание об атаках в рейдах</b>\n'
            f'\n'
        )
    else:
        text = (
            f'<b>🕒 Не проатаковавшие в рейдах</b>\n'
            f'\n'
        )
    raid = await dm.load_raid_weekend()
    if dm.of.state(raid) in ['ongoing', 'ended']:
        AllegedRaidMember = namedtuple(
            typename='AllegedRaidMember', field_names='player_tag attacks_spent attacks_limit'
        )
        alleged_raid_members = []
        for raid_member in raid['members']:
            alleged_raid_members.append(
                AllegedRaidMember(
                    player_tag=raid_member['tag'],
                    attacks_spent=raid_member['attacks'],
                    attacks_limit=raid_member['attackLimit'] + raid_member['bonusAttackLimit']
                )
            )
        rows = await dm.acquired_connection.fetch('''
            SELECT player_tag
            FROM player
            WHERE
                clan_tag = $1
                AND is_player_in_clan
                AND (first_seen < $2 OR (SELECT MIN(first_seen) FROM player WHERE clan_tag = $1) > $2)
                AND NOT (player_tag = any($3::varchar[]))
        ''', dm.clan_tag, dm.of.to_datetime(raid['endTime']), [alleged_raid_member.player_tag
                                                               for alleged_raid_member in alleged_raid_members])
        for row in rows:
            alleged_raid_members.append(
                AllegedRaidMember(player_tag=row['player_tag'], attacks_spent=0, attacks_limit=6)
            )
        text += (
            f'{dm.of.event_datetime(Event.RW, raid['startTime'], raid['endTime'], False)}\n'
            f'\n'
        )
        text += await dm.print_skips(message, alleged_raid_members, ping, attacks_limit=5 if ping else 6)
    else:
        text += 'Информация о рейдах отсутствует\n'
    return text, ParseMode.HTML, None


async def raids_analysis(dm: DatabaseManager) -> Tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    raid = await dm.load_raid_weekend()
    text = (
        f'<b>📊 Анализ атак в рейдах</b>\n'
        f'\n'
    )
    if dm.of.state(raid) in ['ongoing', 'ended']:
        text += (
            f'{dm.of.event_datetime(Event.RW, raid['startTime'], raid['endTime'], True)}\n'
            f'\n'
        )
        RaidAttack = namedtuple(typename='RaidAttack', field_names='attacks_count average_destruction district')
        clan_attacks_by_district = {}
        for attack_log in raid['attackLog']:
            for district in attack_log['districts']:
                if district['destructionPercent'] != 100:
                    continue
                attack_count = district['attackCount']
                if attack_count > 1:
                    average_destruction = district['attacks'][1]['destructionPercent'] / (attack_count - 1)
                else:
                    average_destruction = 100.0
                if district['name'] not in clan_attacks_by_district.keys():
                    clan_attacks_by_district[district['name']] = []
                clan_attacks_by_district[district['name']].append(
                    RaidAttack(attack_count, average_destruction, district)
                )

        for district_name, raid_attacks in clan_attacks_by_district.items():
            text += f'<b>{dm.of.district(district_name)}</b>\n'
            district_best_by_destruction = (
                sorted(raid_attacks, key=lambda ra: (ra.attacks_count, -ra.average_destruction))[0].district
            )
            text += (
                f'👍 Лучшее разрушение '
                f'({dm.of.attacks_count_to_text(len(district_best_by_destruction['attacks']))})\n'
            )
            for attack in district_best_by_destruction['attacks'][::-1]:
                if attack['stars'] == 0:
                    text += f'{dm.of.to_html(attack['attacker']['name'])}: {attack['destructionPercent']}%\n'
                else:
                    text += (
                        f'{dm.of.to_html(attack['attacker']['name'])}: '
                        f'{'⭐' * attack['stars']} ({attack['destructionPercent']}%)\n'
                    )
            district_worst_by_destruction = (
                sorted(raid_attacks, key=lambda ra: (ra.attacks_count, -ra.average_destruction))[-1].district
            )
            text += (
                f'👎 Худшее разрушение '
                f'({dm.of.attacks_count_to_text(len(district_worst_by_destruction['attacks']))})\n'
            )
            for attack in district_worst_by_destruction['attacks'][::-1]:
                if attack['stars'] == 0:
                    text += f'{dm.of.to_html(attack['attacker']['name'])}: {attack['destructionPercent']}%\n'
                else:
                    text += (
                        f'{dm.of.to_html(attack['attacker']['name'])}: '
                        f'{'⭐' * attack['stars']} ({attack['destructionPercent']}%)\n'
                    )
            text += f'\n'
        if len(clan_attacks_by_district) == 0:
            text += f'Список пуст\n'
    else:
        text += 'Информация о рейдах отсутствует\n'
    return text, ParseMode.HTML, None


@router.message(Command('raids_info'))
async def command_raids_info(message: Message, dm: DatabaseManager) -> None:
    text, parse_mode, keyboard = await raids_info(dm)
    await message.reply(text=text, parse_mode=parse_mode, keyboard=keyboard)


@router.message(Command('raids_attacks'))
async def command_raids_attacks(message: Message, dm: DatabaseManager) -> None:
    text, parse_mode, keyboard = await raids_attacks(dm)
    await message.reply(text=text, parse_mode=parse_mode, keyboard=keyboard)


@router.message(Command('raids_skips'))
async def command_raids_skips(message: Message, dm: DatabaseManager) -> None:
    text, parse_mode, keyboard = await raids_skips_raids_ping(dm, message, ping=False)
    await message.reply(text=text, parse_mode=parse_mode, keyboard=keyboard)


@router.message(Command('raids_ping'))
async def command_raids_ping(message: Message, dm: DatabaseManager) -> None:
    user_can_ping_group_members = await dm.can_user_ping_group_members(message.chat.id, message.from_user.id)
    if message.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        await message.reply(text=f'Эта команда работает только в группах')
    elif not user_can_ping_group_members:
        await message.reply(text=f'Эта команда не работает для вас')
    else:
        text, parse_mode, keyboard = await raids_skips_raids_ping(dm, message, ping=True)
        await message.reply(text=text, parse_mode=parse_mode, keyboard=keyboard)


@router.message(Command('raids_analysis'))
async def command_raids_analysis(message: Message, dm: DatabaseManager) -> None:
    text, parse_mode, keyboard = await raids_analysis(dm)
    await message.reply(text=text, parse_mode=parse_mode, keyboard=keyboard)
