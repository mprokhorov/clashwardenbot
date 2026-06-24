-- Adds the dynamic max-townhall attack bonus and the additional-defense-attack bonus
-- to an already deployed clan_war_league_rating_config table.
-- Run once against an existing database created from an older schema.sql.

alter table clan_war_league_rating_config
    add column if not exists attack_max_town_hall_points double precision not null default 0.5,
    add column if not exists attack_max_town_hall_minus_one_points double precision not null default 0.2,
    add column if not exists attack_max_town_hall_minus_two_points double precision not null default 0.05,
    add column if not exists defense_additional_attack_points double precision not null default 0.3;
