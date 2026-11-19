"""
Read-only check: shows tables and columns of the database that are not described in database_manager/schema.sql
(leftovers of old versions and temporary tables) and suggests DROP statements. Nothing is changed.

Run from the bot directory as the bot user:
    sudo -u clashwardenbot .venv/bin/python -m scripts.find_unknown_db_objects
"""
import asyncio
import os
import re

import asyncpg

from config import config

SCHEMA_PATH = os.path.join(os.path.dirname(__file__), '..', 'database_manager', 'schema.sql')


def load_known_columns() -> dict[str, set[str]]:
    with open(SCHEMA_PATH, encoding='utf-8') as file:
        schema_sql = file.read()
    known_columns = {}
    for match in re.finditer(r'create table (\w+)\s*\((.*?)\n\);', schema_sql, re.S):
        known_columns[match.group(1)] = {
            column_match.group(1)
            for column_match in re.finditer(r'^ {4}(\w+)\s+\w+', match.group(2), re.M)
            if column_match.group(1) != 'constraint'
        }
    return known_columns


async def main() -> None:
    bot_schema = config.postgres_schema.get_secret_value()
    known_columns = load_known_columns()
    connection = await asyncpg.connect(
        host=config.postgres_host.get_secret_value(),
        database=config.postgres_database.get_secret_value(),
        user=config.postgres_user.get_secret_value(),
        password=config.postgres_password.get_secret_value()
    )
    tables = await connection.fetch('''
        SELECT
            n.nspname AS schema_name, c.relname AS table_name,
            pg_size_pretty(pg_total_relation_size(c.oid)) AS size,
            s.n_live_tup AS rows,
            COALESCE(s.seq_scan, 0) + COALESCE(s.idx_scan, 0) AS reads,
            COALESCE(s.n_tup_ins, 0) + COALESCE(s.n_tup_upd, 0) + COALESCE(s.n_tup_del, 0) AS writes,
            GREATEST(s.last_autoanalyze, s.last_analyze, s.last_autovacuum, s.last_vacuum) AS last_maintenance
        FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            LEFT JOIN pg_stat_user_tables s ON s.relid = c.oid
        WHERE c.relkind IN ('r', 'p') AND n.nspname NOT IN ('pg_catalog', 'information_schema')
            AND n.nspname NOT LIKE 'pg\\_%'
        ORDER BY n.nspname, c.relname
    ''')
    columns = await connection.fetch('''
        SELECT c.relname AS table_name, a.attname AS column_name, format_type(a.atttypid, a.atttypmod) AS column_type
        FROM pg_attribute a
            JOIN pg_class c ON c.oid = a.attrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = $1 AND c.relkind IN ('r', 'p') AND a.attnum > 0 AND NOT a.attisdropped
        ORDER BY c.relname, a.attnum
    ''', bot_schema)
    stats_reset = await connection.fetchval(
        'SELECT stats_reset FROM pg_stat_database WHERE datname = current_database()'
    )
    await connection.close()

    unknown_tables = [
        table for table in tables
        if table['schema_name'] != bot_schema or table['table_name'] not in known_columns
    ]
    print(f'Bot schema: {bot_schema}. Reads and writes are counted since {stats_reset or "the server start"}\n')
    print('Tables that are not in schema.sql:')
    if not unknown_tables:
        print('  none')
    for table in unknown_tables:
        print(
            f'  {table["schema_name"]}.{table["table_name"]}: {table["size"]}, ~{table["rows"]} rows, '
            f'{table["reads"]} reads, {table["writes"]} writes, last maintenance {table["last_maintenance"]}'
        )

    print('\nColumns of bot tables that are not in schema.sql:')
    unknown_columns = [
        column for column in columns
        if column['table_name'] in known_columns and column['column_name'] not in known_columns[column['table_name']]
    ]
    if not unknown_columns:
        print('  none')
    for column in unknown_columns:
        print(f'  {bot_schema}.{column["table_name"]}.{column["column_name"]} ({column["column_type"]})')

    missing_tables = sorted(set(known_columns) - {table['table_name'] for table in tables if table['schema_name'] == bot_schema})
    if missing_tables:
        print(f'\nTables from schema.sql that are missing in the database: {", ".join(missing_tables)}')

    bot_unknown_tables = [table for table in unknown_tables if table['schema_name'] == bot_schema]
    if bot_unknown_tables or unknown_columns:
        print('\nSuggested statements for the bot schema (NOT executed, check them first):')
        for table in bot_unknown_tables:
            print(f'  DROP TABLE "{bot_schema}"."{table["table_name"]}";')
        for column in unknown_columns:
            print(f'  ALTER TABLE "{bot_schema}"."{column["table_name"]}" DROP COLUMN "{column["column_name"]}";')
    if any(table['schema_name'] != bot_schema for table in unknown_tables):
        print('\nTables outside the bot schema may belong to other programs, no statements are suggested for them')


if __name__ == '__main__':
    asyncio.run(main())
