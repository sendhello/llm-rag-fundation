from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    anthropic_api_key: str = Field(alias="API_KEY")
    max_agent_iterations: int = 5


settings = Settings()