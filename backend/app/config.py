"""应用配置：从环境变量加载。"""
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # LLM
    llm_default_provider: str = "deepseek"
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    deepseek_model: str = "deepseek-chat"
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o-mini"
    qwen_api_key: str = ""
    qwen_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    qwen_model: str = "qwen-plus"

    # JWT
    jwt_secret: str = "change-me-in-production-please-use-a-long-random-string"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440

    # 存储
    sqlite_path: str = "../data/course.db"
    chroma_path: str = "../data/chroma"
    upload_dir: str = "../data/uploads"
    cors_origins: str = "http://localhost:5173,http://localhost:80"

    @property
    def sqlite_url(self) -> str:
        p = Path(self.sqlite_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{p.resolve().as_posix()}"

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
