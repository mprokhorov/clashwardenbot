from dataclasses import dataclass, field
from enum import IntEnum, auto
from typing import Optional


class Hero(IntEnum):
    barbarian_king = auto()
    archer_queen = auto()
    minion_prince = auto()
    grand_warden = auto()
    royal_champion = auto()
    dragon_duke = auto()


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
    dragon_duke_level: int

    def hero_levels_sum(self):
        return self.barbarian_king_level + self.archer_queen_level + self.minion_prince_level + self.grand_warden_level + self.royal_champion_level + self.dragon_duke_level


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
    attack_destruction_points: float
    attack_map_position_points: float
    attack_skip_points: list[float]
    defense_stars_points: list[float]
    defense_destruction_points: float


@dataclass
class HeroEquipment:
    name_in_russian: str
    max_level: int
    hero: Hero


@dataclass
class PlayerRatingConfig:
    minimum_average_cwl_stars: Optional[list[float]]
    minimum_cwl_wars: Optional[int]
    cw_bonus_points: Optional[list[float]]


@dataclass
class PlayerRating:
    player_tag: str
    player_name: str
    is_player_in_family: bool
    town_hall_difference: int
    cwl_clan_tag: Optional[str] = None
    cwl_stars: list[int] = field(default_factory=list)
    cwl_wars: int = 0
    cwl_required_wars: Optional[int] = None
    cwl_required_average_stars: Optional[float] = None
    league_days: dict[int, int] = field(default_factory=dict)
    league_places: list[float] = field(default_factory=list)
    raids_attacks: list[int] = field(default_factory=list)
    raids_gold: list[float] = field(default_factory=list)
    cw_attacks: list[int] = field(default_factory=list)
    is_eligible_for_prize: bool = False
    cwl_points: float = 0
    league_tier_points: float = 0
    league_place_points: float = 0
    raids_attacks_points: float = 0
    raids_gold_points: float = 0
    cw_points: float = 0
    total_points: float = 0
    win_chance: Optional[float] = None

    def cwl_average_stars(self) -> Optional[float]:
        return sum(self.cwl_stars) / self.cwl_wars if self.cwl_wars > 0 else None
