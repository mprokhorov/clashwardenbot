create table action
(
    clan_tag         varchar(16),
    chat_id          bigint,
    user_id          bigint,
    action_timestamp timestamp not null,
    description      text      not null,
    constraint action_bot_user_clan_tag_chat_id_user_id_fk
        foreign key (clan_tag, chat_id, user_id) references bot_user
);

create table activity
(
    clan_tag                         varchar(16) not null
        constraint activity_clan_clan_tag_fk
            references clan,
    name                             varchar(64) not null,
    start_time                       timestamp   not null,
    preparation_message_sent         boolean,
    start_message_sent               boolean,
    half_time_remaining_message_sent boolean,
    end_message_sent                 boolean,
    constraint activity_pk
        primary key (clan_tag, name, start_time)
);

create table blacklisted
(
    chat_id    bigint,
    user_id    bigint,
    clan_tag   varchar(16),
    player_tag varchar(16),
    reason     text not null,
    constraint blacklisted_bot_user_clan_tag_chat_id_user_id_fk
        foreign key (clan_tag, chat_id, user_id) references bot_user,
    constraint blacklisted_player_clan_tag_player_tag_fk
        foreign key (clan_tag, player_tag) references player
);

create table blocked_bot_user
(
    clan_tag varchar(16),
    chat_id  bigint not null,
    user_id  bigint not null,
    constraint blocked_bot_user_pk
        unique (clan_tag, chat_id, user_id),
    constraint blocked_bot_user_bot_user_clan_tag_chat_id_user_id_fk
        foreign key (clan_tag, chat_id, user_id) references bot_user
);

create table bot_user
(
    clan_tag                       varchar(16) not null,
    chat_id                        bigint      not null,
    user_id                        bigint      not null,
    username                       varchar(32),
    first_name                     varchar(64) not null,
    last_name                      varchar(64),
    is_user_in_chat                boolean     not null,
    first_seen                     timestamp,
    last_seen                      timestamp   not null,
    can_use_bot_without_clan_group boolean,
    can_ping_group_members         boolean,
    can_link_group_members         boolean,
    can_edit_cw_list               boolean,
    can_send_messages_from_bot     boolean,
    constraint bot_user_pk
        primary key (clan_tag, chat_id, user_id),
    constraint bot_user_chat_clan_tag_chat_id_fk
        foreign key (clan_tag, chat_id) references chat
);

create table capital_contribution
(
    clan_tag               varchar(16) not null,
    player_tag             varchar(16) not null,
    gold_amount            integer     not null,
    contribution_timestamp timestamp   not null,
    constraint capital_contribution_player_clan_tag_player_tag_fk
        foreign key (clan_tag, player_tag) references player
);

create table chat
(
    clan_tag   varchar(16) not null
        constraint chat_clan_clan_tag_fk
            references clan,
    chat_id    bigint      not null,
    type       varchar(16) not null,
    title      varchar(256),
    username   varchar(256),
    first_name varchar(64),
    last_name  varchar(64),
    constraint chat_pk
        primary key (clan_tag, chat_id)
);

create table clan
(
    clan_tag             varchar(16) not null
        constraint clan_pk
            primary key,
    clan_name            varchar(16) not null,
    main_chat_id         bigint,
    privacy_mode_enabled boolean     not null,
    constraint clan_clan_chat_clan_tag_chat_id_fk
        foreign key (clan_tag, main_chat_id) references clan_chat (clan_tag, chat_id)
);

create table clan_chat
(
    clan_tag              varchar(16)
        constraint clan_chat_clan_clan_tag_fk
            references clan,
    chat_id               bigint,
    send_member_updates   boolean not null,
    send_activity_updates boolean not null,
    consider_donations    boolean not null,
    constraint clan_chat_pk
        unique (clan_tag, chat_id),
    constraint clan_chat_chat_clan_tag_chat_id_fk
        foreign key (clan_tag, chat_id) references chat
);

create table clan_games
(
    clan_tag   varchar(16) not null
        constraint clan_games_clan_clan_tag_fk
            references clan,
    start_time timestamp   not null,
    data       jsonb       not null,
    constraint clan_games_pk
        primary key (clan_tag, start_time)
);

create table clan_war
(
    clan_tag   varchar(16) not null
        constraint clan_war_clan_clan_tag_fk
            references clan,
    start_time timestamp   not null,
    data       jsonb       not null,
    constraint clan_war_pk
        primary key (clan_tag, start_time)
);

create table clan_war_league
(
    clan_tag varchar(16) not null
        constraint clan_war_league_clan_clan_tag_fk
            references clan,
    season   varchar(16) not null,
    data     jsonb       not null,
    constraint clan_war_league_pk
        primary key (clan_tag, season)
);

create table clan_war_league_war
(
    clan_tag varchar(16) not null
        constraint clan_war_league_war_clan_clan_tag_fk
            references clan,
    war_tag  varchar(16) not null,
    season   varchar(16) not null,
    day      integer     not null,
    data     jsonb       not null,
    constraint clan_war_league_war_pk
        primary key (clan_tag, war_tag)
);

create table clan_war_log
(
    clan_tag varchar(16) not null
        constraint clan_war_log_pk
            primary key,
    data     jsonb       not null
);

create table ingore_updates_player
(
    clan_tag   varchar(16) not null,
    player_tag varchar(16) not null,
    constraint ingore_updates_player_pk
        primary key (clan_tag, player_tag),
    constraint ingore_updates_player_player_clan_tag_player_tag_fk
        foreign key (clan_tag, player_tag) references player
);

create table message_bot_user
(
    clan_tag   varchar(16) not null,
    chat_id    bigint      not null,
    message_id bigint      not null,
    user_id    bigint,
    constraint message_bot_user_pk
        unique (clan_tag, chat_id, message_id, user_id),
    constraint message_bot_user_bot_user_clan_tag_chat_id_user_id_fk
        foreign key (clan_tag, chat_id, user_id) references bot_user
);

create table opponent_player
(
    clan_tag             varchar(16) not null,
    player_tag           varchar(16) not null,
    player_name          varchar(16) not null,
    town_hall_level      integer     not null,
    barbarian_king_level integer     not null,
    archer_queen_level   integer     not null,
    grand_warden_level   integer     not null,
    royal_champion_level integer     not null,
    constraint opponent_player_pk
        primary key (clan_tag, player_tag)
);

create table player
(
    clan_tag                    varchar(16) not null
        constraint player_clan_clan_tag_fk
            references clan,
    player_tag                        varchar(16) not null,
    player_name                       varchar(16) not null,
    is_player_in_clan                 boolean     not null,
    is_player_set_for_clan_wars       boolean     not null,
    is_player_set_for_clan_war_league boolean     not null,
    barbarian_king_level              integer     not null,
    archer_queen_level                integer     not null,
    grand_warden_level                integer     not null,
    royal_champion_level              integer     not null,
    town_hall_level                   integer     not null,
    builder_hall_level                integer     not null,
    home_village_trophies             integer     not null,
    builder_base_trophies             integer     not null,
    player_role                       varchar(16) not null,
    capital_gold_contributed          integer     not null,
    donations_given                   integer     not null,
    donations_received                integer     not null,
    first_seen                        timestamp,
    last_seen                         timestamp   not null,
    constraint player_pk
        primary key (clan_tag, player_tag)
);

create table player_bot_user
(
    clan_tag   varchar(16),
    player_tag varchar(16),
    chat_id    bigint,
    user_id    bigint,
    constraint player_bot_user_pk
        unique (clan_tag, player_tag, chat_id, user_id),
    constraint player_bot_user_bot_user_clan_tag_chat_id_user_id_fk
        foreign key (clan_tag, chat_id, user_id) references bot_user,
    constraint player_bot_user_player_clan_tag_player_tag_fk
        foreign key (clan_tag, player_tag) references player
);

create table raid_weekend
(
    clan_tag   varchar(16) not null
        constraint raid_weekend_clan_clan_tag_fk
            references clan,
    start_time timestamp   not null,
    data       jsonb       not null,
    constraint raid_weekend_pk
        primary key (clan_tag, start_time)
);

create table war_win_streak
(
    clan_tag       varchar(16) not null
        constraint war_win_streak_pk
            primary key,
    war_win_streak integer     not null
);