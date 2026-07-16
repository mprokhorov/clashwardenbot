"""Тесты логики рейтинга игроков на фейковой БД. Запуск: python tests/test_player_ratings.py"""
import asyncio
import json
import os
import sys
from datetime import date, datetime

os.environ.update({
    'TELEGRAM_API_CLIENT_NAME': 'x', 'TELEGRAM_API_ID': '1', 'TELEGRAM_API_HASH': 'x',
    'TELEGRAM_BOT_OWNER_ID': '1',
    'CLASH_OF_CLANS_API_LOGIN': 'x', 'CLASH_OF_CLANS_API_PASSWORD': 'x',
    'CLASH_OF_CLANS_API_KEY_NAME': 'x', 'CLASH_OF_CLANS_API_KEY_DESCRIPTION': 'x',
    'POSTGRES_HOST': 'x', 'POSTGRES_DATABASE': 'x', 'POSTGRES_SCHEMA': 'x',
    'POSTGRES_USER': 'x', 'POSTGRES_PASSWORD': 'x',
    'FREQUENT_JOBS_FREQUENCY_MINUTES': '1', 'INFREQUENT_JOBS_FREQUENCY_MINUTES': '10',
    'JOB_TIMESPAN_SECONDS': '10',
    'WEBHOOK_HOST': 'x', 'WEBHOOK_PATH': '/x', 'WEBAPP_HOST': '::', 'WEBAPP_PORT': '1',
    'CLAN_TAGS': '["#AAA"]', 'TELEGRAM_BOT_API_TOKENS': '["1:x"]',
    'TOWN_HALL_EMOJI_IDS': json.dumps(['1'] * 16),
    'BUILDER_HALL_EMOJI_IDS': json.dumps(['1'] * 10),
    'HOME_VILLAGE_HERO_EMOJI_IDS': json.dumps(['1'] * 4),
    'CAPITAL_GOLD_EMOJI_ID': '1', 'RAID_MEDAL_EMOJI_ID': '1',
})
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
os.chdir(REPO_ROOT)

from database_manager import DatabaseManager
from output_formatter import OutputFormatter

SEASON = '2026-07'

CWL_WARS_AAA = [
    {'day': 0, 'data': json.dumps({
        'state': 'warEnded', 'preparationStartTime': '20260701T000000.000Z',
        'clan': {'tag': '#AAA', 'members': [
            {'tag': '#P1', 'attacks': [{'stars': 3}]},
            {'tag': '#P2', 'attacks': [{'stars': 1}]},
        ]},
        'opponent': {'tag': '#OPP1', 'members': []},
    })},
    {'day': 1, 'data': json.dumps({
        'state': 'warEnded', 'preparationStartTime': '20260702T000000.000Z',
        'clan': {'tag': '#AAA', 'members': [
            {'tag': '#P1', 'attacks': [{'stars': 3}]},
        ]},
        'opponent': {'tag': '#OPP2', 'members': []},
    })},
    # war in preparation: must not be counted
    {'day': 2, 'data': json.dumps({
        'state': 'preparation', 'preparationStartTime': '20260703T000000.000Z',
        'clan': {'tag': '#AAA', 'members': [
            {'tag': '#P1'}, {'tag': '#P2'},
        ]},
        'opponent': {'tag': '#OPP3', 'members': []},
    })},
]

RAID_WEEKENDS = [
    # one raid weekend, both family clans participated
    {'start_time': datetime(2026, 7, 3), 'data': json.dumps({'members': [
        {'tag': '#P1', 'capitalResourcesLooted': 50000, 'attacks': 6},
        {'tag': '#P2', 'capitalResourcesLooted': 12000, 'attacks': 3},
        {'tag': '#P4', 'capitalResourcesLooted': 30000, 'attacks': 6},
    ]})},
    {'start_time': datetime(2026, 7, 3), 'data': json.dumps({'members': [
        {'tag': '#P3', 'capitalResourcesLooted': 20000, 'attacks': 5},
    ]})},
]

CLAN_WARS = [
    {'clan_tag': '#AAA', 'data': json.dumps({
        'state': 'warEnded', 'endTime': '2026-07-10T00:00:00',
        'clan': {'members': [
            {'tag': '#P1', 'attacks': [{}, {}]},
            {'tag': '#P2', 'attacks': []},
        ]},
    })},
]

PLAYER_ROWS = [
    {'player_tag': '#P1', 'clan_tag': '#AAA', 'town_hall_level': 17},
    {'player_tag': '#P2', 'clan_tag': '#AAA', 'town_hall_level': 16},
    {'player_tag': '#P3', 'clan_tag': '#BBB', 'town_hall_level': 15},
]

LEAGUE_ROWS = [
    # day 1: P1 and P3 tie (same league, same trophies), P2 lower
    {'player_tag': '#P1', 'league_date': date(2026, 7, 1), 'league_tier': 36, 'trophies': 5000},
    {'player_tag': '#P3', 'league_date': date(2026, 7, 1), 'league_tier': 36, 'trophies': 5000},
    {'player_tag': '#P2', 'league_date': date(2026, 7, 1), 'league_tier': 33, 'trophies': 3000},
    # day 2: only P1
    {'player_tag': '#P1', 'league_date': date(2026, 7, 2), 'league_tier': 35, 'trophies': 4900},
    # P3 has a duplicate reading from the other clan the same day: best must win
    {'player_tag': '#P3', 'league_date': date(2026, 7, 1), 'league_tier': 35, 'trophies': 4000},
]

CONFIG_ROWS = [
    {'child_clan_tag': '#AAA', 'minimum_average_cwl_stars': [2.5, 2.4, 2.1, 2.0], 'minimum_cwl_wars': 1,
     'cw_bonus': [-3, -1, 0]},
    {'child_clan_tag': '#BBB', 'minimum_average_cwl_stars': None, 'minimum_cwl_wars': None, 'cw_bonus': None},
]


class FakeConnection:
    async def fetch(self, query, *args):
        if 'FROM child_clan' in query:
            return [{'child_clan_tag': '#BBB'}]
        if 'FROM raid_weekend' in query:
            return RAID_WEEKENDS
        if 'FROM player_bot_user' in query or 'player_bot_user' in query:
            return []
        if 'cw_bonus IS NOT NULL' in query and 'FROM player_rating_config' in query:
            return [
                {'child_clan_tag': r['child_clan_tag'], 'cw_bonus': r['cw_bonus']}
                for r in CONFIG_ROWS if r['cw_bonus'] is not None
            ]
        if 'FROM player_rating_config' in query:
            assert args[0] == '#AAA', f'config must be looked up by family root, got {args[0]}'
            return CONFIG_ROWS
        if 'FROM clan_war_league_war' in query:
            return CWL_WARS_AAA if args[0] == '#AAA' else []
        if 'FROM clan_war' in query:
            return CLAN_WARS
        if 'FROM player_league' in query:
            return LEAGUE_ROWS
        if 'FROM player' in query:
            return PLAYER_ROWS
        raise AssertionError(f'unexpected query: {query}')

    async def fetchval(self, query, *args):
        if 'MAX(town_hall_level)' in query:
            return 17
        if 'SELECT father_clan_tag' in query:
            return '#AAA' if args[0] == '#BBB' else None
        raise AssertionError(f'unexpected fetchval: {query}')


async def main():
    dm = object.__new__(DatabaseManager)
    dm.clan_tag = '#AAA'
    dm.of = OutputFormatter()
    dm.acquired_connection = FakeConnection()

    ratings = await dm.get_player_ratings(SEASON)

    assert set(ratings) == {'#P1', '#P2', '#P3'}, f'unexpected players: {set(ratings)}'
    p1, p2, p3 = ratings['#P1'], ratings['#P2'], ratings['#P3']

    # P4 left the family: excluded even though he raided
    assert '#P4' not in ratings

    # eligibility
    assert p1.is_eligible_for_prize, 'P1 must be eligible (avg 3.0 >= 2.5, wars 2 >= 1)'
    assert not p2.is_eligible_for_prize, 'P2 must not be eligible (avg 1.0 < 2.4)'
    assert p3.is_eligible_for_prize, 'P3 must be auto-eligible (clan without CWL requirements)'

    # CWL: preparation war must not count
    assert p1.cwl_total_wars == 2 and p1.cwl_total_stars == 6, (p1.cwl_total_wars, p1.cwl_total_stars)
    assert p2.cwl_total_wars == 1 and p2.cwl_total_stars == 1
    assert abs(p1.total_cwl_points - 6 / 21 * 55) < 1e-9

    # raids: single weekend, no linked users -> raw gold
    assert p1.raids_total_attacks == [6] and p1.raids_total_gold == [50000]
    assert abs(p1.total_raids_points - (3 + 7)) < 1e-9, p1.total_raids_points
    assert abs(p2.total_raids_points - (3 / 6 * 3 + 1)) < 1e-9, p2.total_raids_points
    assert p3.raids_total_attacks == [5] and p3.raids_total_gold == [20000]

    # league: day 1 P1/P3 tie for places 1-2 -> 5 points each; day 2 P1 alone -> 10
    assert p1.leagues_places == [(1, 2), (1, 1)] or p1.leagues_places == [(1, 1), (1, 2)], p1.leagues_places
    assert abs(p1.total_place_points - 15 / 31) < 1e-9, p1.total_place_points
    assert abs(p3.total_place_points - 5 / 31) < 1e-9, p3.total_place_points
    assert p2.total_place_points == 0, 'P2 is not eligible: no place points'
    # best-of-day reading for P3 must be (36, 5000), not (35, 4000)
    assert p3.league_numbers == [36], p3.league_numbers
    # league points: P1 day1 tier36 = 20, day2 tier35 = 15
    assert abs(p1.total_league_points - 35 / 31) < 1e-9
    assert abs(p2.total_league_points - 5 / 31) < 1e-9

    # CW penalties: P1 2 attacks -> 0, P2 0 attacks -> -3
    assert p1.total_cw_penalty_points == 0
    assert p2.total_cw_penalty_points == -3
    assert p2.cw_total_attacks == [0]

    # totals add up
    for tag, r in ratings.items():
        expected = (
            r.total_cwl_points + r.total_league_points + r.total_place_points +
            r.total_raids_points + r.total_cw_penalty_points
        )
        assert abs(r.total_points - expected) < 1e-9, tag

    print('ALL ASSERTIONS PASSED')
    for tag, r in sorted(ratings.items(), key=lambda x: x[1].total_points, reverse=True):
        print(f'{tag}: total={r.total_points:.3f} eligible={r.is_eligible_for_prize}')


asyncio.run(main())


async def test_from_child_clan():
    dm = object.__new__(DatabaseManager)
    dm.clan_tag = '#BBB'  # дочерний клан
    dm.of = OutputFormatter()
    dm.acquired_connection = FakeConnection()
    ratings = await dm.get_player_ratings(SEASON)
    assert set(ratings) == {'#P1', '#P2', '#P3'}, set(ratings)
    assert abs(ratings['#P1'].total_points - 27.327) < 0.001, ratings['#P1'].total_points
    assert ratings['#P3'].is_eligible_for_prize
    print('CHILD CLAN VIEW OK (identical family rating)')

asyncio.run(test_from_child_clan())

# --- router views test ---
from routers.player_rating import (
    player_rating_list, player_rating_choose, player_rating_details, player_rating_seasons,
    PlayerRatingCallbackFactory, OutputView
)

_orig_fetch = FakeConnection.fetch
async def fetch_with_seasons(self, query, *args):
    if 'DISTINCT TO_CHAR(league_date' in query:
        return [{'season': '2026-06'}, {'season': '2026-07'}]
    return await _orig_fetch(self, query, *args)
FakeConnection.fetch = fetch_with_seasons


async def test_views():
    dm = object.__new__(DatabaseManager)
    dm.clan_tag = '#AAA'
    dm.of = OutputFormatter()
    dm.acquired_connection = FakeConnection()
    dm.name = {'#P1': 'Alice', '#P2': 'Bob', '#P3': 'Carol'}

    text, mode, kb = await player_rating_list(dm, None)
    assert 'только допущенные' in text and 'Alice' in text and 'Bob' not in text, text
    rows = kb.inline_keyboard
    assert [b.text for b in rows[0]] == ['📋 Подробнее', '🔽 Развернуть', '🔄 Обновить'], [b.text for b in rows[0]]
    assert [b.text for b in rows[-1]] == ['⬅️ Июнь 2026', '🧾 Все сезоны'], [b.text for b in rows[-1]]
    print('list view (default, eligible only) OK')

    cb = PlayerRatingCallbackFactory(output_view=OutputView.player_rating_list, season='2026-07', eligible_only=False)
    text, mode, kb = await player_rating_list(dm, cb)
    assert 'все игроки' in text and 'Bob' in text
    assert '🔼 Свернуть' in [b.text for b in kb.inline_keyboard[0]]
    print('list view (expanded) OK')

    cb = PlayerRatingCallbackFactory(output_view=OutputView.player_rating_list, season='2026-06')
    text, mode, kb = await player_rating_list(dm, cb)
    assert [b.text for b in kb.inline_keyboard[-1]] == ['➡️ Июль 2026', '🧾 Все сезоны'], [b.text for b in kb.inline_keyboard[-1]]
    print('list view (past season nav) OK')

    cb = PlayerRatingCallbackFactory(output_view=OutputView.player_rating_choose, season='2026-07')
    text, mode, kb = await player_rating_choose(dm, cb)
    assert 'Выберите игрока' in text
    assert any('Alice' in b.text for row in kb.inline_keyboard for b in row)
    print('choose view OK')

    cb = PlayerRatingCallbackFactory(
        output_view=OutputView.player_rating_details, season='2026-07', player_tag='#P1', eligible_only=True
    )
    text, mode, kb = await player_rating_details(dm, cb)
    print('--- details ---')
    print(text)
    assert 'Допуск к розыгрышу: ✅' in text
    assert 'Войн ЛВК: 2 ⚔️ / 1 ⚔️' in text
    assert 'Среднее количество звёзд: 3 ⭐ / 2.5 ⭐' in text
    assert 'Легенда I — 1 день, Легенда II — 1 день' in text
    assert 'Места в клане: #1-2, #1' in text
    assert 'Атак: 6 🗡️' in text and 'Золота: 50 000 🟡' in text
    print('details view OK')

    cb = PlayerRatingCallbackFactory(output_view=OutputView.player_rating_seasons, season='2026-07')
    text, mode, kb = await player_rating_seasons(dm, cb)
    labels = [b.text for row in kb.inline_keyboard for b in row]
    assert labels == ['Июль 2026', 'Июнь 2026', '🔄 Обновить'], labels
    print('seasons view OK')

asyncio.run(test_views())
