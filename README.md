# LLM RAG Foundation

A hands-on FastAPI playground for learning the **Anthropic Claude API**: structured output via `tool_use`, token streaming over Server-Sent Events, and prompt caching. This repo is the *foundation* layer — a thin, readable codebase — on top of which a real Retrieval-Augmented Generation service will be built.

> Status: educational / learning log. Not production-ready.

---

## What you'll learn from this code

- How to **force a JSON-shaped response** from Claude by passing a Pydantic JSON Schema as a `tool` and pinning `tool_choice` to it.
- How to **stream tokens** from `messages.stream` and adapt them to the SSE `data: ... \n\n` framing that browsers and `EventSource` consumers expect.
- How **ephemeral prompt caching** works in practice — including reading `cache_creation_input_tokens` vs `cache_read_input_tokens` from the usage payload.
- How to **wire an async Anthropic client into FastAPI** through `Depends`, so each request gets a fresh repository without leaking state.

---

## Status & Roadmap

| | |
|---|---|
| ✅ Done | 3 endpoints, structured extraction (haiku), SSE chat streaming (sonnet), prompt-cached code review (sonnet) |
| 🚧 Next | Embedding pipeline, vector store, retrieval-augmented `/ask` endpoint, evals |

The `rag` in the repo name is a deliberate forward-reference — see the [Roadmap](#roadmap) section at the bottom.

---

## Endpoints

| Method | Path | What it demonstrates |
|---|---|---|
| `POST` | `/extract` | Structured extraction — turns a free-form job description into a typed `JobInfo` object. |
| `POST` | `/chat/stream` | Streaming — yields model tokens as Server-Sent Events. |
| `POST` | `/analyze` | Code review with **prompt caching** enabled (`cache_control: ephemeral`). |

Interactive docs are live at [`/docs`](http://localhost:8000/docs) (Swagger) and [`/redoc`](http://localhost:8000/redoc) once the server is running.

---

## Models in use

| Endpoint | Claude model | Why |
|---|---|---|
| `/extract` | `claude-haiku-4-5` | Cheapest, fastest model — extraction is short, deterministic, schema-bound. |
| `/chat/stream` | `claude-sonnet-4-6` | Balanced quality for open-ended chat. |
| `/analyze` | `claude-sonnet-4-6` | Stronger reasoning for code review; prompt caching amortises re-reads of large code blobs. |

The `ClaudeModel` enum in [ai.py](ai.py) also lists `claude-opus-4-7` and `claude-mythos-preview` — they are wired but currently unused, ready to be swapped in for experiments.

---

## Project structure

```
llm-rag-foundation/
├── main.py          # FastAPI app + 3 endpoints, DI via Depends(get_clause_repo)
├── ai.py            # ClaudeRepo — async Anthropic client wrapper, one method per endpoint
├── schema.py        # Pydantic models: JobInfo (tool input_schema), Chat, ReviewResult
├── settings.py      # pydantic-settings — reads API_KEY env var
├── pyproject.toml   # Poetry config, Python ^3.14
├── .env.example     # Template — copy to .env and fill in API_KEY
└── README.md
```

---

## Setup

Requires **Python 3.14** and **Poetry**.

```bash
# 1. Install dependencies
poetry install

# 2. Configure your Anthropic key
cp .env.example .env
echo "API_KEY=sk-ant-..." > .env   # or edit by hand

# 3. Run the dev server
poetry run uvicorn main:app --reload
```

The server starts on `http://localhost:8000`. Open `/docs` for the Swagger UI.

> The env var is called `API_KEY` (not `ANTHROPIC_API_KEY`) — see [settings.py](settings.py).

---

## API examples (curl)

### `POST /extract` — structured extraction

```bash
curl -X POST http://localhost:8000/extract \
  -H "Content-Type: application/json" \
  -d '{
    "text": "Senior Python Engineer at Acme Co. (Melbourne, hybrid). Build async services with FastAPI and Postgres. Visa sponsorship available. AUD 150-180k."
  }'
```

Trimmed response:

```json
{
  "job_title": "Senior Python Engineer",
  "job_type": "permanent_full_time",
  "company_name": "Acme Co.",
  "city": "Melbourne",
  "job_flexibility": "hybrid",
  "key_skills": ["Python", "FastAPI", "Postgres", "async"],
  "salary": "AUD 150-180k",
  "is_available_sponsorship": true
}
```

### `POST /chat/stream` — SSE streaming

```bash
curl -N -X POST http://localhost:8000/chat/stream \
  -H "Content-Type: application/json" \
  -d '{"chat_id": "demo-1", "message": "In one sentence, what is RAG?"}'
```

The `-N` disables curl's output buffering so you see tokens arrive live:

```
data: Retrieval-Augmented

data:  Generation combines a

data:  retriever with an LLM ...

data: [DONE]
```

### `POST /analyze` — code review with prompt caching

Note: `/analyze` takes `code` as a **query parameter** (it's declared as a bare `str` in the route, not a Pydantic model), so URL-encode the snippet:

```bash
curl -X POST "http://localhost:8000/analyze?code=def%20add(a,b):%0A%20%20%20%20return%20a+b"
```

Trimmed response:

```json
{
  "reviews": [
    {
      "line": 1,
      "code_of_line": "def add(a,b):",
      "review": "Missing type hints; PEP 8 recommends a space after the comma."
    }
  ]
}
```

Server logs reveal the caching effect — on the second identical call, watch `cache_read_input_tokens` jump and `cache_creation_input_tokens` drop to zero.

---

## Notes on Claude API usage (the non-obvious bits)

**Why `tools` + `tool_choice` instead of asking for JSON in the prompt.**
Claude's `tools` mechanism takes a JSON Schema (here, generated by `JobInfo.model_json_schema()`) and **forces** the model to emit a `tool_use` block whose `input` validates against that schema. By pinning `tool_choice={"type": "tool", "name": "extract_job_info"}` we guarantee the model invokes our tool rather than returning prose — no fragile post-hoc JSON parsing required.

**Why `temperature=0.0` on extraction.**
Extraction has a single correct answer per field. Zero temperature gives reproducible output and makes regressions easier to spot during evals.

**SSE framing.**
The `text_stream` generator from `client.messages.stream(...)` yields plain text chunks. To make them consumable by browser `EventSource` / `htmx` SSE / OpenAI-style clients, each chunk is wrapped in `data: <text>\n\n` and the stream is terminated with `data: [DONE]\n\n`. The blank line after each `data:` is part of the SSE protocol — not a typo.

**Prompt caching.**
Passing `cache_control={"type": "ephemeral"}` to `messages.create` asks Anthropic to cache the prefix of the prompt for ~5 minutes. On a cache hit you pay a discounted price on those tokens and skip the per-token compute. The two new fields in `response.usage` tell you what happened:

- `cache_creation_input_tokens` — tokens **written** into the cache this turn (first call after a change).
- `cache_read_input_tokens` — tokens **served from** the cache (subsequent calls).

For a code-review service that re-reads the same long snippet across follow-ups, this is a substantial latency and cost win.

---

## Roadmap

The next phase turns this foundation into a real RAG service:

- **Document ingestion** — chunking strategies (fixed-size, semantic, recursive), token accounting.
- **Embedding store** — likely PGVector or Qdrant; benchmarking recall vs cost.
- **Retrieval layer** — hybrid search (dense + BM25), reranking with a cross-encoder.
- **`POST /ask` endpoint** — retrieve top-k chunks, stuff them into a Claude prompt as cached context (great fit for prompt caching), stream the answer with inline citations.
- **Evals** — a small golden set + an LLM-as-judge to track regressions as the retrieval pipeline changes.
