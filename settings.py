from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    anthropic_api_key: str = Field(alias="API_KEY")
    max_agent_iterations: int = 5
    max_concurrent_requests: int = 5
    max_input_chars: int = 50000


settings = Settings()
