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
    openai_base_url: str = "https://jeniya.top/v1"
    openai_model: str = "gpt-4o-mini"
    gemini_api_key: str = ""
    gemini_base_url: str = "https://jeniya.top/v1"
    gemini_model: str = "gemini-3.5-flash"
    claude_api_key: str = ""
    claude_base_url: str = "https://jeniya.top/v1"
    claude_model: str = "claude-sonnet-5"
    qwen_api_key: str = ""
    qwen_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    qwen_model: str = "qwen-plus"
    moonshot_api_key: str = ""
    moonshot_base_url: str = "https://api.moonshot.cn/v1"
    moonshot_model: str = "moonshot-v1-8k"
    zhipu_api_key: str = ""
    zhipu_base_url: str = "https://open.bigmodel.cn/api/paas/v4"
    zhipu_model: str = "glm-4-flash"

    # JWT
    jwt_secret: str = "change-me-in-production-please-use-a-long-random-string"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440

    # 存储
    sqlite_path: str = "../data/course.db"
    chroma_path: str = "../data/chroma"
    upload_dir: str = "../data/uploads"
    cors_origins: str = "http://localhost:5173,http://localhost:80"
    ffmpeg_path: str = ""

    @property
    def sqlite_url(self) -> str:
        p = Path(self.sqlite_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{p.resolve().as_posix()}"

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
