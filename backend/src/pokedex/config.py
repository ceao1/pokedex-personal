from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql://postgres:postgres@127.0.0.1:54322/postgres"
    tcgdex_base_url: str = "https://api.tcgdex.net/v2/en"
    supabase_url: str = "http://127.0.0.1:54321"
    supabase_secret_key: str = ""
    storage_bucket: str = "card-photos"
    # Base que se le entrega al NAVEGADOR para subir y descargar fotos. Tiene
    # que ser distinta de `supabase_url` en cuanto la app se abre desde otro
    # dispositivo: para el celular, `127.0.0.1` es el propio celular, así que
    # una URL firmada con loopback es imposible de usar y la foto nunca sube.
    # Vacía = misma que `supabase_url`, que es lo correcto en escritorio.
    storage_public_url: str = ""


settings = Settings()
