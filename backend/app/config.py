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

    # 短信验证码（阿里云 PNVS 短信认证；SMS_DEV_MODE=1 时不真正发送，固定码 123456）
    sms_dev_mode: bool = True
    sms_dev_code: str = "123456"
    sms_code_ttl_seconds: int = 300
    sms_send_interval_seconds: int = 60
    sms_max_verify_attempts: int = 5
    aliyun_sms_access_key_id: str = ""
    aliyun_sms_access_key_secret: str = ""
    aliyun_pnvs_sign_name: str = ""
    aliyun_pnvs_template_code: str = ""

    # 存储
    sqlite_path: str = "../data/course.db"
    chroma_path: str = "../data/chroma"
    upload_dir: str = "../data/uploads"
    cors_origins: str = "http://localhost:5173,http://localhost:80"
    ffmpeg_path: str = ""

    # 本地视频 ASR / 切片（自研；课设主路径）
    # tiny 快但中文易糊；base/small 更准。改模型后需对视频重新索引。
    whisper_model: str = "base"
    whisper_language: str = "zh"
    # 领域提示可明显改善课件术语识别（人名、语法点等）
    whisper_initial_prompt: str = (
        "这是一段大学计算机编程课程讲解。内容涉及 C 语言、指针、数组、函数、循环、"
        "结构体、字符串、Dennis Ritchie、Unix、编译、调试。"
    )
    video_chunk_seconds: int = 30
    video_chunk_gap_sec: float = 1.8  # 字幕静音间隙超过该值则切段
    video_chunk_overlap_sec: int = 4  # 相邻聚合段文本时间重叠，提高边界命中

    # 知识推送
    knowledge_push_hour: int = 8
    knowledge_push_minute: int = 0
    knowledge_push_limit: int = 3
    search_api_key: str = ""  # 可选 Bing Web Search；留空则仅用 RSS

    @property
    def sqlite_url(self) -> str:
        p = Path(self.sqlite_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{p.resolve().as_posix()}"

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
