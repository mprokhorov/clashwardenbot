from dataclasses import dataclass
from enum import IntEnum, auto
from typing import Optional


class Hero(IntEnum):
    barbarian_king = auto()
    archer_queen = auto()
    minion_prince = auto()
    grand_warden = auto()
    royal_champion = auto()


@dataclass
class ClanMember:
    clan_tag: str
    player_tag: str
    town_hall_level: int
    barbarian_king_level: int
    archer_queen_level: int
    minion_prince_level: int
    grand_warden_level: int
    royal_champion_level: int

    def hero_levels_sum(self):
        return self.barbarian_king_level + self.archer_queen_level + self.minion_prince_level + self.grand_warden_level + self.royal_champion_level


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


@dataclass
class CWLWPlayerRating:
    attack_new_stars: int
    attack_destruction_percentage: int
    attack_map_position: int
    defense_stars: int
    defense_destruction_percentage: int


@dataclass
class CWLPlayerRating:
    attack_new_stars: list[int]
    attack_destruction_percentage: list[int]
    attack_map_position: list[int]
    defense_stars: list[int]
    defense_destruction_percentage: list[int]
    bonus_points: list[float]
    total_attack_new_stars_points: Optional[float]
    total_attack_destruction_percentage_points: Optional[float]
    total_attack_map_position_points: Optional[float]
    total_attack_skips_points: Optional[float]
    total_defense_stars_points: Optional[float]
    total_defense_destruction_percentage_points: Optional[float]
    total_bonus_points: Optional[float]
    total_points: Optional[float]


@dataclass
class CWLRatingConfig:
    attack_stars_points: list[float]
    attack_desruction_points: float
    attack_map_position_points: float
    attack_skip_points: list[float]
    defense_stars_points: list[float]
    defense_desruction_points: float


@dataclass
class HeroEquipment:
    name_in_russian: str
    max_level: int
    hero: Hero
