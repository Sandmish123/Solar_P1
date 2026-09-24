from pydantic import model_validator
from pydantic_settings import BaseSettings
from functools import lru_cache

DEFAULT_SECRET_KEY = "change-this-in-production"


class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite:///./solar_reports.db"
    APP_ENV: str = "development"
    SECRET_KEY: str = DEFAULT_SECRET_KEY

    class Config:
        env_file = ".env"
        extra = "ignore"

    @model_validator(mode="after")
    def _production_needs_a_real_secret(self):
        # SECRET_KEY signs the session cookie. Shipping the published default would
        # let anyone forge a login, so refuse to boot rather than run insecurely.
        if self.is_production and self.SECRET_KEY == DEFAULT_SECRET_KEY:
            raise ValueError("SECRET_KEY must be set to a private value when APP_ENV=production")
        return self

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"

    @property
    def db_connect_args(self) -> dict:
        if self.DATABASE_URL.startswith("sqlite"):
            return {"check_same_thread": False}
        return {}


@lru_cache
def get_settings() -> Settings:
    return Settings()
