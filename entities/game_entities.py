from dataclasses import dataclass
from typing import Optional


@dataclass
class ClanMember:
    player_tag: str
    town_hall_level: int
    barbarian_king_level: int
    archer_queen_level: int
    grand_warden_level: int
    royal_champion_level: int


@dataclass
class WarMember:
    player_tag: str
    attacks_spent: int
    attacks_limit: int


@dataclass
class RaidsAttack:
    attacks_count: int
    average_destruction: float
    district: str


@dataclass
class RaidsMember:
    player_tag: str
    attacks_spent: int
    attacks_limit: int
    gold_looted: Optional[int] = None


@dataclass
class ClanWarLeagueWar:
    clan_tag: str
    war_tag: str
    season: str
    day: int


@dataclass
class ClanWarLeagueMember:
    town_hall_level: int
    map_position: int


@dataclass
class ClanWarLeagueClan:
    clan_name: str
    town_hall_levels: list[int]
    average_town_hall_level: float
