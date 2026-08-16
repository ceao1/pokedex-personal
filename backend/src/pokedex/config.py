from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql://postgres:postgres@127.0.0.1:54322/postgres"
    tcgdex_base_url: str = "https://api.tcgdex.net/v2/en"
    supabase_url: str = "http://127.0.0.1:54321"
    supabase_secret_key: str = ""
    storage_bucket: str = "card-photos"


settings = Settings()
