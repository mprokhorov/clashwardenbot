CREATE TABLE IF NOT EXISTS monospace_player_tag
(
    clan_tag   varchar(16) NOT NULL
        REFERENCES clan (clan_tag),
    player_tag varchar(16) NOT NULL,
    CONSTRAINT monospace_player_tag_pk PRIMARY KEY (clan_tag, player_tag)
);

CREATE TABLE IF NOT EXISTS bot_message_log
(
    clan_tag   varchar(16) NOT NULL
        REFERENCES clan (clan_tag),
    chat_id    bigint      NOT NULL,
    message_id bigint      NOT NULL,
    html_text  text        NOT NULL,
    created_at timestamp   NOT NULL DEFAULT now(),
    CONSTRAINT bot_message_log_pk PRIMARY KEY (clan_tag, chat_id, message_id)
);
