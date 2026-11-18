-- Applied automatically at bot startup (DatabaseManager.apply_migrations). Must stay idempotent.

ALTER TABLE bot_user ADD COLUMN IF NOT EXISTS can_run_player_rating_giveaway boolean;

CREATE TABLE IF NOT EXISTS non_clickable_player_name
(
    player_name varchar(16) not null
        constraint non_clickable_player_name_pk
            primary key
);

INSERT INTO non_clickable_player_name (player_name)
VALUES ('ard.man')
ON CONFLICT DO NOTHING;

CREATE TABLE IF NOT EXISTS player_rating_draw
(
    draw_id          serial
        constraint player_rating_draw_pk
            primary key,
    clan_tag         varchar(16) not null,
    season           varchar(7)  not null,
    chat_id          bigint      not null,
    message_id       bigint      not null,
    user_id          bigint      not null,
    created_at       timestamp   not null,
    seed             varchar(64) not null,
    seed_hash        varchar(64) not null,
    participants     jsonb       not null,
    client_seed      text,
    ticket           bigint,
    winner_tag       varchar(16),
    drawn_by_user_id bigint,
    drawn_at         timestamp,
    cancelled_at     timestamp,
    constraint player_rating_draw_chat_id_message_id_key
        unique (chat_id, message_id)
);
