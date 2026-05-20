from fastapi import FastAPI, Depends
from fastapi.responses import StreamingResponse
from anthropic import Anthropic
from ai import ClaudeRepo, get_clause_repo
import logging

from schema import JobInfo, JobDescription, Chat, ReviewResult

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


app = FastAPI(
    title="Job Description Extractor",
    description="A simple API for extracting job information from job descriptions.",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)


@app.post("/extract")
async def extract(
    job_description: JobDescription, clause_repo: ClaudeRepo = Depends(get_clause_repo)
) -> JobInfo:
    job_info = await clause_repo.extract_job_info(job_description.text)
    return job_info


@app.post("/chat/stream")
async def chat_stream(
    chat: Chat, clause_repo: ClaudeRepo = Depends(get_clause_repo),
) -> StreamingResponse:
    return StreamingResponse(clause_repo.send_to_chat(chat), media_type="text/event-stream")


@app.post("/analyze")
async def analyze(
    code: str, clause_repo: ClaudeRepo = Depends(get_clause_repo),
) -> ReviewResult:
    return await clause_repo.analise(code)
