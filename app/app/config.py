from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    admin_api_token: str = ""
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.8-flash"
    cohere_api_key: str = ""
    cohere_embed_model: str = "embed-v4.0"
    cohere_rerank_model: str = "rerank-v4.0-fast"
    cohere_embed_dim: int = 1536
    knowledge_dir: str = "./knowledge"
    whatsapp_verify_token: str = ""
    whatsapp_access_token: str = ""
    whatsapp_phone_number_id: str = ""
    whatsapp_app_secret: str = ""
    whatsapp_api_version: str = ""
    top_k: int = 12
    min_relevance: float = 0.25
    worker_poll_seconds: float = 1.0


settings = Settings()


