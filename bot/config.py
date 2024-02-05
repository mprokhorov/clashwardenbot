from pydantic import SecretStr
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    telegram_bot_api_token: SecretStr
    telegram_bot_username: SecretStr
    telegram_api_client_name: SecretStr
    telegram_api_id: SecretStr
    telegram_api_hash: SecretStr

    webhook_host: SecretStr
    webhook_path: SecretStr
    webapp_host: SecretStr
    webapp_port: SecretStr

    clash_of_clans_api_login: SecretStr
    clash_of_clans_api_password: SecretStr
    clash_of_clans_api_key_name: SecretStr
    clash_of_clans_api_key_description: SecretStr

    postgres_host: SecretStr
    postgres_database: SecretStr
    postgres_user: SecretStr
    postgres_password: SecretStr

    telegram_chat_id: SecretStr
    clash_of_clans_clan_tag: SecretStr

    class Config:
        env_file = 'bot/.env'
        env_file_encoding = 'utf-8'


config = Settings()
