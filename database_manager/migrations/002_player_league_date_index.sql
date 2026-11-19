-- Applied automatically at bot startup (DatabaseManager.apply_migrations). Must stay idempotent.

-- The player rating reads one month of league results of the clan family
CREATE INDEX IF NOT EXISTS player_league_clan_tag_league_date_index
    ON player_league (clan_tag, league_date);
