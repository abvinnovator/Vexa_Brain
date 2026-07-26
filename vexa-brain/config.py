from pydantic_settings import BaseSettings
from pathlib import Path

class Settings(BaseSettings):
    groq_api_key: str
    mongodb_uri: str = "mongodb://localhost:27017/vexa"
    mongodb_db_name: str = "vexa"
    llm_model: str = "groq/compound-mini"
    llm_temperature: float = 0.3
    llm_max_tokens: int = 2048
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = True

    # Knowledge base config
    knowledge_base_dir: str = str(Path(__file__).parent / "knowledge")

    # LangSmith tracing config
    langsmith_api_key: str = ""
    langsmith_project: str = "XA"
    langsmith_tracing: bool = True

    class Config:
        env_file = ".env"
        case_sensitive = False
        extra = "ignore"

settings = Settings()
