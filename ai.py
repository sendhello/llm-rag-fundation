from typing import Generator, AsyncGenerator

from anthropic import AsyncAnthropic
from anthropic.types import Message, Model
from fastapi.exceptions import ValidationException
from prompts import REVIEW_SYSTEM_PROMPT

from settings import Settings
from schema import JobInfo, Chat, ReviewResult, ReviewResultElement
from enum import StrEnum
import logging


logger = logging.getLogger(__name__)


class ClaudeModel(StrEnum):
    haiku = "claude-haiku-4-5"
    sonnet = "claude-sonnet-4-6"
    opus = "claude-opus-4-7"
    mythos = "claude-mythos-preview"


class ClaudeRepo:
    def __init__(self):
        self._settings = Settings()
        self._client = AsyncAnthropic(api_key=self._settings.anthropic_api_key.strip(), max_retries=3)

    async def extract_job_info(self, job_description: str) -> JobInfo:
        tools = [{
            "name": "extract_job_info",
            "description": "Extract job information from a job description.",
            "input_schema": JobInfo.model_json_schema(),
        }]
        response = await self._client.messages.create(
            model=ClaudeModel.haiku.value,
            max_tokens=1024,
            system="You are a helpful assistant that extracts job information from a job description.",
            messages=[{
                "role": "user",
                "content": f"Job description: {job_description}",
            }],
            tools=tools,
            tool_choice={"type": "tool", "name": "extract_job_info"},
            temperature=0.0,
        )
        logger.info(f"{response.usage.input_tokens} input and {response.usage.output_tokens} output tokens used.")
        if response.stop_reason != "tool_use":
            logger.error(f"Stop reason is `{response.stop_reason}`")
            raise ValidationException("Stop reason is not `tool_use`")

        tool_use_block = next(c for c in response.content if c.type == "tool_use")
        return JobInfo.model_validate(tool_use_block.input)

    async def send_to_chat(self, chat: Chat) -> AsyncGenerator[str, None]:
        async with self._client.messages.stream(
            model=ClaudeModel.sonnet.value,
            max_tokens=1024,
            messages=[{
                "role": "user",
                "content": chat.message,
            }],
        ) as stream:
            async for message in stream.text_stream:
                yield f"data: {message}\n\n"

            yield "data: [DONE]\n\n"

    async def analise(self, code: str) -> ReviewResult:
        tools = [{
            "name": "code_review",
            "description": "Code review a piece of code.",
            "input_schema": ReviewResult.model_json_schema(),
        }]
        response = await self._client.messages.create(
            model=ClaudeModel.sonnet.value,
            max_tokens=1024,
            system=[{
                "type": "text",
                "text": REVIEW_SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{
                "role": "user",
                "content": f"{code}",
            }],
            tools=tools,
            tool_choice={"type": "tool", "name": "code_review"},
        )
        logger.info(f"{response.usage.input_tokens=}")
        logger.info(f"{response.usage.output_tokens=}")
        logger.info(f"{response.usage.cache_creation_input_tokens=}")
        logger.info(f"{response.usage.cache_read_input_tokens=}")
        if response.stop_reason != "tool_use":
            logger.error(f"Stop reason is `{response.stop_reason}`")
            raise ValidationException("Stop reason is not `tool_use`")

        tool_use_block = next(c for c in response.content if c.type == "tool_use")
        return ReviewResult.model_validate(tool_use_block.input)



async def get_clause_repo() -> ClaudeRepo:
    return ClaudeRepo()
