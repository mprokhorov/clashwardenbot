from pydantic import SecretStr
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    telegram_api_client_name: SecretStr
    telegram_api_id: SecretStr
    telegram_api_hash: SecretStr

    clash_of_clans_api_login: SecretStr
    clash_of_clans_api_password: SecretStr
    clash_of_clans_api_key_name: SecretStr
    clash_of_clans_api_key_description: SecretStr

    postgres_host: SecretStr
    postgres_database: SecretStr
    postgres_user: SecretStr
    postgres_password: SecretStr

    webhook_host: SecretStr
    webhook_path: SecretStr
    webapp_host: SecretStr
    webapp_port: SecretStr

    clan_tags: list[SecretStr]
    telegram_bot_api_tokens: list[SecretStr]
    telegram_bot_usernames: list[SecretStr]
    bot_owner_user_id: SecretStr

    class Config:
        env_file = 'bot/.env'
        env_file_encoding = 'utf-8'


config = Settings()
