-- Applied automatically at bot startup (DatabaseManager.apply_migrations). Must stay idempotent.

-- Raids have a reminder one day before the end besides the one 12 hours before
ALTER TABLE activity ADD COLUMN IF NOT EXISTS day_remaining_message_sent boolean;
