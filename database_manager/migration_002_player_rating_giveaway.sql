-- Adds the /player_rating_giveaway command's permission flag and draw history table.
-- Run once against an existing database created from an older schema.sql.

alter table bot_user
    add column if not exists can_start_player_rating_giveaway boolean;

create table if not exists player_rating_giveaway
(
    id                  serial      not null
        constraint player_rating_giveaway_pk
            primary key,
    clan_tag            varchar(16) not null
        constraint player_rating_giveaway_clan_clan_tag_fk
            references clan,
    chat_id             bigint      not null,
    season              varchar(16) not null,
    started_by_user_id  bigint      not null,
    created_at          timestamp   not null,
    seed                varchar(64) not null,
    roll                double precision not null,
    entries             jsonb       not null,
    winner_player_tag   varchar(16) not null
);
