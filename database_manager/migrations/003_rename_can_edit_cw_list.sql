-- Applied automatically at bot startup (DatabaseManager.apply_migrations). Must stay idempotent.

-- The permission covers the CW list, the CWL list and CWL rating bonuses, not only the CW list
DO $$
BEGIN
    IF EXISTS (
        SELECT FROM information_schema.columns
        WHERE table_schema = current_schema() AND table_name = 'bot_user' AND column_name = 'can_edit_cw_list'
    ) THEN
        ALTER TABLE bot_user RENAME COLUMN can_edit_cw_list TO can_edit_war_lists;
    END IF;
END $$;
