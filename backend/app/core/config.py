from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # 数据库配置
    postgres_server: str = "localhost"
    postgres_user: str = "agent_user"
    postgres_password: str = "agent_password"
    postgres_db: str = "agent_db"
    postgres_port: int = 5432

    @property
    def database_url(self) -> str:
        # 异步 SQLAlchemy 使用的 URL 格式
        return f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}@{self.postgres_server}:{self.postgres_port}/{self.postgres_db}"

    # Redis 配置
    redis_host: str = "localhost"
    redis_port: int = 6379

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
