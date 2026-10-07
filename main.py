from typing import Any

from pydantic import BaseModel
from pydantic_settings.sources.providers import aws

from settings import settings
from fastapi import FastAPI, Depends, Request
from contextlib import asynccontextmanager
from fastapi.responses import StreamingResponse
from anthropic import Anthropic
from starlette.responses import JSONResponse
from utils import chunk_by_paragraphs
from semantic_search import async_embed
from vector_search import get_session, Document, purge_database, create_database, search_similar

from ai import ClaudeRepo, get_clause_repo
import logging

from schema import JobInfo, JobDescription, Chat, ReviewResult

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI) -> Any:
    await create_database()
    try:
        yield
    finally:
        # await purge_database()
        pass


app = FastAPI(
    title="Job Description Extractor",
    description="A simple API for extracting job information from job descriptions.",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)


@app.post("/extract")
async def extract(
    job_description: JobDescription, clause_repo: ClaudeRepo = Depends(get_clause_repo)
) -> JobInfo:
    job_info = await clause_repo.extract_job_info(job_description.text)
    return job_info


@app.post("/chat/stream")
async def chat_stream(
    chat: Chat,
    request: Request,
    clause_repo: ClaudeRepo = Depends(get_clause_repo),
) -> StreamingResponse:
    return StreamingResponse(
        clause_repo.send_to_chat(request=request, chat=chat),
        media_type="text/event-stream",
    )


@app.post("/analyze")
async def analyze(
    code: str,
    clause_repo: ClaudeRepo = Depends(get_clause_repo),
) -> ReviewResult:
    if len(code) > settings.max_input_chars:
        return JSONResponse(
            status_code=400,
            content={
                "error": f"Input exceeds maximum length of {settings.max_input_chars} characters."
            },
        )

    return await clause_repo.analyze(code)


@app.post("/agent")
async def agent(
    text: str = "Find Python jobs in Melbourne and check if they offer sponsorship",
    clause_repo: ClaudeRepo = Depends(get_clause_repo),
) -> dict[str, str]:
    if len(text) > settings.max_input_chars:
        return JSONResponse(
            status_code=400,
            content={
                "error": f"Input exceeds maximum length of {settings.max_input_chars} characters."
            },
        )

    return {"text": await clause_repo.agent(text)}


class Body(BaseModel):
    text: str


@app.post("/rag/index")
async def index(
    body: Body,
    clause_repo: ClaudeRepo = Depends(get_clause_repo),
    session=Depends(get_session),
) -> JSONResponse:
    """
    - Receives a text input
    - Performs chunking (semantic, with overlap)
    - Batch embeddings
    - Save to vector database (PGVector)
    """
    text = body.text
    if len(text) > settings.max_index_input_chars:
        return JSONResponse(
            status_code=400,
            content={
                "error": f"Input exceeds maximum length of {settings.max_index_input_chars} characters."
            },
        )

    total_chunks = chunk_by_paragraphs(text)
    embed_chunks_collection = []
    logger.debug(f"Chunks: {total_chunks}")
    logger.info(f"Embedding {len(total_chunks)} chunks...")
    chunks = total_chunks
    while len(chunks) > 300:
        current_chunk = chunks[:300]
        chunks = chunks[300:]
        embed_chunks_collection.append(await async_embed(current_chunk))

    embed_chunks_collection.append(await async_embed(chunks))
    embed_chunks = [item for sublist in embed_chunks_collection for item in sublist]
    logger.info(f"Indexing {len(embed_chunks)} chunks...")

    for chunk, embedding in zip(total_chunks, embed_chunks):
        session.add(Document(content=chunk, embedding=embedding, doc_metadata={}))

    await session.commit()

    return JSONResponse(
        status_code=201,
        content={"status": "success"},
    )


@app.post("/rag/query")
async def query(
    text: str,
    clause_repo: ClaudeRepo = Depends(get_clause_repo),
    session=Depends(get_session),
) -> JSONResponse:
    """
    - Embedding request
    - Retrieval top-20
    - Re-ranking up to top-5
    - Augmentation (XML-structure, cache system prompt)
    - Generation with citation
    - Return with sources
    """
    if len(text) > settings.max_input_chars:
        return JSONResponse(
            status_code=400,
            content={
                "error": f"Input exceeds maximum length of {settings.max_input_chars} characters."
            },
        )

    # Embed the query
    [embed_query] = await async_embed([text])

    # Retrieve the top 20 results
    search_result = await search_similar(session, embed_query, top_k=20)
    candidates = [document for document, _ in search_result]
    logger.info(f"Retrieved {len(candidates)} candidates")

    # Re-rank the results
    ranked_results = await clause_repo.rerank(text, candidates)

    # Argumentation and generation
    result = await clause_repo.generate_answer(query=text, chunks=ranked_results)

    return JSONResponse(
        status_code=200,
        content=result,
    )
