from pydantic import BaseModel, Field, RootModel
from enum import StrEnum
from typing import Literal
from settings import settings


class JobType(StrEnum):
    permanent_full_time = "permanent_full_time"
    temporary = "temporary"
    contract = "contract"
    internship = "internship"
    volunteer = "volunteer"
    part_time = "part_time"
    freelance = "freelance"


class JobFlexibility(StrEnum):
    on_site = "on_site"
    hybrid = "hybrid"
    remote = "remote"


class JobInfo(BaseModel):
    job_title: str | None
    job_type: JobType | None = None
    company_name: str | None
    city: str | None = None
    state: str | None = None
    job_flexibility: JobFlexibility | None = None
    responsibilities: list[str] = Field(default_factory=list)
    key_skills: list[str] = Field(default_factory=list)
    salary: str | None = None
    job_url: str | None = None
    company_url: str | None = None
    benefits: list[str] = Field(default_factory=list)
    is_available_sponsorship: bool = False
    company_description: str | None = None


class JobDescription(BaseModel):
    text: str = Field(
        ...,
        description="The full text of the job description to be analyzed.",
        max_length=settings.max_input_chars,
    )


class Chat(BaseModel):
    chat_id: str
    message: str = Field(
        ...,
        description="The message to be sent to the chat model.",
        max_length=settings.max_input_chars,
    )


class ReviewResultElement(BaseModel):
    line: int | None = Field(
        None, description="The line number of the code that was reviewed."
    )
    code_of_line: str | None = Field(
        None, description="The code line that was reviewed."
    )
    review: str | None = Field(None, description="The review of the code line.")


class ReviewResult(BaseModel):
    reviews: list[ReviewResultElement]
