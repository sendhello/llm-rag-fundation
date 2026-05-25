import asyncio
from asyncio import Semaphore
from contextlib import asynccontextmanager
from typing import Generator, AsyncGenerator, Any
import json
from anthropic import AsyncAnthropic, omit, APIError
from anthropic.types import Message, Model, ToolUseBlock
from fastapi.exceptions import ValidationException
from prompts import REVIEW_SYSTEM_PROMPT
from fastapi import Request
from settings import settings, Settings
from schema import JobInfo, Chat, ReviewResult, ReviewResultElement
from enum import StrEnum
import logging
import inspect
from pydantic import create_model


logger = logging.getLogger(__name__)


TOOL_REGISTRY = {}


class ClaudeModel(StrEnum):
    haiku = "claude-haiku-4-5"
    sonnet = "claude-sonnet-4-6"
    opus = "claude-opus-4-7"
    mythos = "claude-mythos-preview"


PRICING = {
    ClaudeModel.haiku: {"input": 1.00, "output": 5.00},  # $ per 1M токенов
    ClaudeModel.sonnet: {"input": 3.00, "output": 15.00},
    ClaudeModel.opus: {"input": 5.00, "output": 25.00},
}


def calculate_cost(model: ClaudeModel, usage) -> float:
    price = PRICING[model]
    input_cost = (usage.input_tokens / 1_000_000) * price["input"]
    output_cost = (usage.output_tokens / 1_000_000) * price["output"]
    # Cache read ~10% от input цены
    cache_cost = (
        ((usage.cache_read_input_tokens or 0) / 1_000_000) * price["input"] * 0.1
    )
    return input_cost + output_cost + cache_cost


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


class AnthropicClient:
    def __init__(self):
        self._client = AsyncAnthropic(
            api_key=settings.anthropic_api_key.strip(), max_retries=3
        )
        self._semaphore = Semaphore(settings.max_concurrent_requests)

    async def create_message(
        self,
        model: ClaudeModel,
        messages: list[dict[str, Any]],
        max_tokens: int = 1024,
        system: str | list[dict] | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: dict[str, Any] | None = None,
        temperature: float | None = None,
    ):
        async with self._semaphore:
            response = await self._client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system or omit,
                messages=messages,
                tools=tools or omit,
                tool_choice=tool_choice or omit,
                temperature=temperature or omit,
            )
            return response

    @asynccontextmanager
    async def stream(
        self,
        model: ClaudeModel,
        messages: list[dict[str, Any]],
        max_tokens: int = 1024,
        system: str | None = None,
    ):
        async with self._semaphore:
            async with self._client.messages.stream(
                model=model,
                max_tokens=max_tokens,
                messages=messages,
                system=system or omit,
            ) as stream:
                yield stream


class ClaudeRepo:
    def __init__(self):
        self._client = AnthropicClient()

    async def extract_job_info(self, job_description: str) -> JobInfo:
        model = ClaudeModel.haiku
        tools = [
            {
                "name": "extract_job_info",
                "description": "Extract job information from a job description.",
                "input_schema": JobInfo.model_json_schema(),
            }
        ]
        response = await self._client.create_message(
            model=model,
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
        cost = calculate_cost(model, response.usage)
        logger.info(
            f"input={response.usage.input_tokens}, "
            f"output={response.usage.output_tokens}, "
            f"cache_read={response.usage.cache_read_input_tokens or 0}"
            f"Total cost: ${cost:.6f}"
        )

        if response.stop_reason != "tool_use":
            logger.error(f"Stop reason is `{response.stop_reason}`")
            raise ValidationException("Stop reason is not `tool_use`")

        tool_use_block = next(c for c in response.content if c.type == "tool_use")
        return JobInfo.model_validate(tool_use_block.input)

    async def send_to_chat(
        self, request: Request, chat: Chat
    ) -> AsyncGenerator[str, None]:
        """Send a message to the chat and stream the response back to the client."""

        try:
            async with self._client.stream(
                model=ClaudeModel.sonnet,
                max_tokens=1024,
                messages=[
                    {
                        "role": "user",
                        "content": chat.message,
                    }
                ],
            ) as stream:
                async for message in stream.text_stream:
                    if request.is_disconnected():
                        logger.info("Client disconnected, stopping stream.")
                        break

                    yield f"data: {message}\n\n"

        except APIError as e:
            logger.error(f"Anthropic API error: {e}")
            yield f"data: [ERROR] {str(e)}\n\n"

        finally:
            yield "data: [DONE]\n\n"
            full_message = await stream.get_final_message()
            cost = calculate_cost(ClaudeModel.sonnet, full_message.usage)
            logger.info(
                f"input={full_message.usage.input_tokens}, "
                f"output={full_message.usage.output_tokens}, "
                f"cache_read={full_message.usage.cache_read_input_tokens or 0}"
                f"Total cost: ${cost:.6f}"
            )

    async def analyze(self, code: str) -> ReviewResult:
        model = ClaudeModel.sonnet
        tools = [
            {
                "name": "code_review",
                "description": "Code review a piece of code.",
                "input_schema": ReviewResult.model_json_schema(),
            }
        ]
        response = await self._client.create_message(
            model=model,
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
        cost = calculate_cost(model, response.usage)
        logger.info(
            f"input={response.usage.input_tokens}, "
            f"output={response.usage.output_tokens}, "
            f"cache_read={response.usage.cache_read_input_tokens or 0}"
            f"Total cost: ${cost:.6f}"
        )

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
        model = ClaudeModel.sonnet
        messages = [{"role": "user", "content": user_message}]
        for iteration in range(max_iterations):
            response = await self._client.create_message(
                model=model,
                max_tokens=4096,
                system=system_prompt,
                tools=tools,
                messages=messages,
            )
            messages.append({"role": "assistant", "content": response.content})
            cost = calculate_cost(model, response.usage)
            logger.info(
                f"Iteration {iteration}: \n"
                f"input={response.usage.input_tokens}, \n"
                f"output={response.usage.output_tokens}, \n"
                f"cache_read={response.usage.cache_read_input_tokens or 0} \n"
                f"Total cost: ${cost:.6f}"
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
        prompt_text = ("You are a helpful assistant that can use tools to answer user "
                "questions regarding job search and salary information. "
                "Answer like a mate with jokes, not use table. ") * 50  # multiply for test cache
        system_prompt = [
            {
                "type": "text",
                "text": prompt_text,
                "cache_control": {"type": "ephemeral"},
            }
        ]
        tools = [function_to_tool_schema(t) for t in TOOL_REGISTRY.values()]
        return await self._run_agent(
            user_message=user_message,
            tools=tools,
            system_prompt=system_prompt,
            max_iterations=settings.max_agent_iterations,
        )


async def get_clause_repo() -> ClaudeRepo:
    return ClaudeRepo()
