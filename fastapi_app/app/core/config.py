from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # --- app metadata ---
    # Set by Compose from .env so the image tag stays in sync with the env.
    # Not used by the app — declared here so pydantic's extras=forbid passes.
    app_version: str = ""

    # --- database ---
    postgres_user: str = "myuser"
    postgres_password: str  # required — must come from .env
    postgres_db: str = "ardesigndb"
    postgres_host: str = "db"
    postgres_port: int = 5432

    # --- redis / celery ---
    redis_url: str = "redis://redis:6379/0"
    # Image launched by the Celery worker for model conversion. Override in
    # .env to pin a release or roll back without changing application code.
    converter_image: str = "ismayilovh/ardesign-converter:latest"

    # --- media storage ---
    media_root: str = "/app/media"
    media_volume_name: str = "ardesign_media_data"

    # --- Hunyuan3D image-to-3D service ---
    # Host-native API server (patched api_server.py). Worker reaches it via
    # the Docker host-gateway alias on Linux.
    hunyuan_base_url: str = "http://host.docker.internal:8081"
    hunyuan_total_timeout: int = 900   # seconds — overall wall clock cap per generation

    # --- JWT ---
    jwt_secret_key: str  # required — must come from .env
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    # --- CORS ---
    cors_origins: str = "http://localhost:5173"

    # --- debug ---
    debug: bool = False

    @property
    def database_url(self) -> str:
        """Async URL for FastAPI (asyncpg driver)."""
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def sync_database_url(self) -> str:
        """Sync URL for Celery workers (psycopg2 driver)."""
        return (
            f"postgresql+psycopg2://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    class Config:
        env_file = ".env"


settings = Settings()
