from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

# 动态计算 .env 的绝对路径
# config.py 的路径是 backend/app/core/config.py
# parents[0]=core, parents[1]=app, parents[2]=backend, parents[3]=hhyy(项目根目录)
BASE_DIR = Path(__file__).resolve().parents[3]
ENV_FILE = BASE_DIR / ".env"


class Settings(BaseSettings):
    secret_key: str = "SECRET_KEY"
    # --- DeepSeek 配置 ---
    deepseek_api_key: str
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    deepseek_chat_model: str = "deepseek-flash"

    # --- 数据库配置 ---
    postgres_server: str = "localhost"
    postgres_user: str = "agent_user"
    postgres_password: str = "agent_password"
    postgres_db: str = "agent_db"
    postgres_port: int = 5432

    # --- Redis 配置 ---
    redis_host: str = "localhost"
    redis_port: int = 6379

    @property
    def database_url(self) -> str:
        return f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}@{self.postgres_server}:{self.postgres_port}/{self.postgres_db}"

    # 强制指定读取绝对路径的 .env
    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore"
    )


settings = Settings()
