from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Literal


class Settings(BaseSettings):
    claude_api_key: str
    voyage_api_key: str
    openai_api_key: str
    embed_model: Literal["voyage", "openai", "transform"] = "openai"
    max_agent_iterations: int = 5
    max_concurrent_requests: int = 5
    max_input_chars: int = 50000


settings = Settings()
