import asyncio
from typing import Generator, AsyncGenerator, Any
import json
from anthropic import AsyncAnthropic
from anthropic.types import Message, Model, ToolUseBlock
from fastapi.exceptions import ValidationException
from prompts import REVIEW_SYSTEM_PROMPT

from settings import settings, Settings
from schema import JobInfo, Chat, ReviewResult, ReviewResultElement
from enum import StrEnum
import logging
import inspect
from pydantic import create_model


logger = logging.getLogger(__name__)


TOOL_REGISTRY = {}


def tool(func):
    """Decorator to register a tool function"""
    TOOL_REGISTRY[func.__name__] = func
    return func


def function_to_tool_schema(func) -> dict:
    """Convert a Python function to a tool schema for Anthropic API"""

    sig = inspect.signature(func)
    hints = func.__annotations__

    properties = {}
    required = []
    to_json_schema_map = {
        str: "string",
        int: "integer",
        float: "number",
        bool: "boolean",
        list: "array",
        dict: "object",
    }

    for name, param in sig.parameters.items():
        if name == "return":
            continue
        python_type = hints.get(name, str)
        json_type = to_json_schema_map.get(python_type, "string")
        properties[name] = {"type": json_type}
        if param.default == inspect.Parameter.empty:
            required.append(name)

    return {
        "name": func.__name__,
        "description": func.__doc__ or "",
        "input_schema": {
            "type": "object",
            "properties": properties,
            "required": required,
        },
    }


@tool
async def search_jobs(city: str) -> list[dict[str, Any]]:
    """Search for jobs in a given city."""
    return [
        {
            "title": "Software Engineer",
            "company": "Google",
            "location": "Mountain View, CA",
        },
        {
            "title": "Data Scientist",
            "company": "Facebook",
            "location": "Menlo Park, CA",
        },
        {"title": "Product Manager", "company": "Amazon", "location": "Seattle, WA"},
    ]


@tool
async def get_salary_data(role: str, company_name: str) -> tuple[int, int]:
    """Return salary diapason: from, to."""
    return 90000, 120000


@tool
async def check_sponsorship(company_name: str) -> bool:
    """Sponsorship check."""
    return True


class ClaudeModel(StrEnum):
    haiku = "claude-haiku-4-5"
    sonnet = "claude-sonnet-4-6"
    opus = "claude-opus-4-7"
    mythos = "claude-mythos-preview"


class ClaudeRepo:
    def __init__(self):
        self._client = AsyncAnthropic(
            api_key=settings.anthropic_api_key.strip(), max_retries=3
        )

    async def extract_job_info(self, job_description: str) -> JobInfo:
        tools = [
            {
                "name": "extract_job_info",
                "description": "Extract job information from a job description.",
                "input_schema": JobInfo.model_json_schema(),
            }
        ]
        response = await self._client.messages.create(
            model=ClaudeModel.haiku.value,
            max_tokens=1024,
            system="You are a helpful assistant that extracts job information from a job description.",
            messages=[
                {
                    "role": "user",
                    "content": f"Job description: {job_description}",
                }
            ],
            tools=tools,
            tool_choice={"type": "tool", "name": "extract_job_info"},
            temperature=0.0,
        )
        logger.info(
            f"{response.usage.input_tokens} input and {response.usage.output_tokens} output tokens used."
        )
        if response.stop_reason != "tool_use":
            logger.error(f"Stop reason is `{response.stop_reason}`")
            raise ValidationException("Stop reason is not `tool_use`")

        tool_use_block = next(c for c in response.content if c.type == "tool_use")
        return JobInfo.model_validate(tool_use_block.input)

    async def send_to_chat(self, chat: Chat) -> AsyncGenerator[str, None]:
        async with self._client.messages.stream(
            model=ClaudeModel.sonnet.value,
            max_tokens=1024,
            messages=[
                {
                    "role": "user",
                    "content": chat.message,
                }
            ],
        ) as stream:
            async for message in stream.text_stream:
                yield f"data: {message}\n\n"

            yield "data: [DONE]\n\n"

    async def analyze(self, code: str) -> ReviewResult:
        tools = [
            {
                "name": "code_review",
                "description": "Code review a piece of code.",
                "input_schema": ReviewResult.model_json_schema(),
            }
        ]
        response = await self._client.messages.create(
            model=ClaudeModel.sonnet.value,
            max_tokens=1024,
            system=[
                {
                    "type": "text",
                    "text": REVIEW_SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[
                {
                    "role": "user",
                    "content": f"{code}",
                }
            ],
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

    @staticmethod
    async def _execute_tool(name: str, input: dict) -> Any:
        """Execute a tool by name with the given input."""

        if name not in TOOL_REGISTRY:
            raise ValueError(f"{name} not in TOOL_REGISTRY")

        return await TOOL_REGISTRY[name](**input)

    async def _safety_execute_tool(self, block: ToolUseBlock) -> Any:
        """Execute a tool use block safely, with error handling."""

        try:
            result = await self._execute_tool(block.name, block.input)
            return {
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": json.dumps(result, ensure_ascii=False),
            }
        except Exception as e:
            logger.error(f"Error executing tool {block.name}: {e}")
            return {
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": f"Error executing tool {block.name}: {str(e)}",
                "is_error": True,
            }

    async def _run_agent(
        self,
        user_message: str,
        tools: list[dict],
        system_prompt: str,
        max_iterations: int = settings.max_agent_iterations,
    ) -> str:
        messages = [{"role": "user", "content": user_message}]
        for iteration in range(max_iterations):
            logger.debug(f"Agent iteration {iteration} with messages: {messages}")

            response = await self._client.messages.create(
                model=ClaudeModel.sonnet.value,
                max_tokens=4096,
                system=system_prompt,
                tools=tools,
                messages=messages,
            )
            messages.append({"role": "assistant", "content": response.content})
            logger.info(
                f"Iteration {iteration}: {response.usage.input_tokens} input and {response.usage.output_tokens} output tokens used."
            )

            if response.stop_reason == "tool_use":
                tool_use_blocks = [c for c in response.content if c.type == "tool_use"]
                logger.info(f"Tool use blocks: {tool_use_blocks}")
                tool_use_results = await asyncio.gather(
                    *[self._safety_execute_tool(block) for block in tool_use_blocks]
                )
                messages.append({"role": "user", "content": list(tool_use_results)})
                continue

            elif response.stop_reason == "end_turn":
                text_blocks = [c for c in response.content if c.type == "text"]
                return text_blocks[-1].text if text_blocks else ""

            raise ValidationException(f"Unexpected stop reason: {response.stop_reason}")
        else:
            raise ValidationException("Max iterations reached without end_turn.")

    async def agent(
        self,
        user_message: str,
    ) -> str:
        system_prompt = "You are a helpful assistant that can use tools to answer user questions regarding job search and salary information. Answer like a mate with joyks, not use table."
        tools = [function_to_tool_schema(t) for t in TOOL_REGISTRY.values()]
        return await self._run_agent(
            user_message=user_message,
            tools=tools,
            system_prompt=system_prompt,
            max_iterations=settings.max_agent_iterations,
        )


async def get_clause_repo() -> ClaudeRepo:
    return ClaudeRepo()
