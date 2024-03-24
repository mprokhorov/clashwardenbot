from pydantic import SecretStr
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    telegram_api_client_name: SecretStr
    telegram_api_id: SecretStr
    telegram_api_hash: SecretStr

    telegram_bot_owner_id: SecretStr

    clash_of_clans_api_login: SecretStr
    clash_of_clans_api_password: SecretStr
    clash_of_clans_api_key_name: SecretStr
    clash_of_clans_api_key_description: SecretStr

    postgres_host: SecretStr
    postgres_database: SecretStr
    postgres_schema: SecretStr
    postgres_user: SecretStr
    postgres_password: SecretStr

    frequent_jobs_frequency_minutes: SecretStr
    infrequent_jobs_frequency_minutes: SecretStr
    job_timespan_seconds: SecretStr

    webhook_host: SecretStr
    webhook_path: SecretStr
    webapp_host: SecretStr
    webapp_port: SecretStr

    clan_tags: list[SecretStr]
    telegram_bot_api_tokens: list[SecretStr]

    town_hall_emoji_ids: list[SecretStr]
    builder_hall_emoji_ids: list[SecretStr]
    home_village_hero_emoji_ids: list[SecretStr]
    capital_gold_emoji_id: SecretStr
    raid_medal_emoji_id: SecretStr

    class Config:
        env_file = '.env'
        env_file_encoding = 'utf-8'


config = Settings()
