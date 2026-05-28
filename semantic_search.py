from dotenv.variables import Literal
from openai import OpenAI
from sentence_transformers import SentenceTransformer
from voyageai import Client
import numpy as np
from settings import settings

QUERY = "remote job with visa support"
VACANCIES = [
    "Senior Python Developer with FastAPI experience, fully remote position, competitive salary.",
    "Backend Engineer (Python/Django) — work from anywhere in the world, flexible hours.",
    "Data Engineer needed: ClickHouse, Kafka, dbt. Hybrid office in Berlin, 3 days on-site.",
    "Looking for a Go developer to build microservices. Strictly on-site in London, no remote.",
    "Machine Learning Engineer, PyTorch and LLM fine-tuning, distributed team across EU timezones.",
    "Frontend React developer, TypeScript, Next.js. Remote within Europe only.",
    "DevOps Engineer — Kubernetes, Terraform, AWS. Office-based role in Munich, relocation package provided.",
    "Full-stack JavaScript engineer (Node.js + Vue). Remote-first company, async culture.",
    "Junior QA Automation Engineer, Selenium and Playwright. On-site in Warsaw, no visa sponsorship available.",
    "Site Reliability Engineer with strong Linux background, 24/7 on-call rotation, hybrid in Amsterdam.",
    "AI Research Scientist focused on RAG systems and vector databases. Distributed team, work from any location.",
    "Database Administrator for PostgreSQL and ClickHouse clusters, remote position, EU residency required.",
    "Solidity smart contract developer, DeFi protocol, fully decentralized team — work from anywhere.",
    "iOS Engineer (Swift, SwiftUI), Apple ecosystem expert. Hybrid in Cupertino, relocation supported.",
    "Technical Writer for developer documentation, Python and API references. Remote, any timezone.",
    "Product Manager with B2B SaaS background, on-site in New York, visa sponsorship offered for the right candidate.",
    "Cybersecurity Analyst — SIEM, threat hunting, incident response. Remote within US only.",
    "Junior Data Analyst with SQL and Tableau skills. Office-based in Singapore, entry-level salary.",
    "Embedded systems engineer (C/C++, RTOS), automotive industry. On-site in Stuttgart, relocation paid.",
    "Cloud Architect (GCP, multi-region), 10+ years experience. Remote-friendly, contract or full-time.",
]


openai = OpenAI(api_key=settings.openai_api_key)
transformer = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
voyageai = Client(api_key=settings.voyage_api_key)

EMBEDDED_DATA = []

def _openai_embed(text: str) -> list[float]:
    response = openai.embeddings.create(
        model="text-embedding-3-large",
        input=text,
    )
    return response.data[0].embedding


def _voyage_embed(text: str) -> list[float]:
    return voyageai.embed([text], model="voyage-4-large").embeddings[0]


def _transform_embed(text: str) -> list[float]:
    return transformer.encode(text).tolist()


EMBED_MAP = {
    "voyage": _voyage_embed,
    "openai": _openai_embed,
    "transform": _transform_embed,
}


def embed(text: str, embed_model: str = settings.embed_model) -> list[float]:
    if embed_model not in EMBED_MAP:
        raise ValueError(f"Invalid embed type: {embed_model}")

    return EMBED_MAP[embed_model](text)


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))


def search(query, top_k=3, embed_model: str = settings.embed_model):
    embedded_query = embed(query, embed_model=embed_model)
    print(
        f"Searching for {top_k} most similar documents to query '{query}' using {embed_model}..."
    )
    scores = [cosine_similarity(embedded_query, e_doc) for e_doc in EMBEDDED_DATA]
    top_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:top_k]
    return [(i, scores[i], VACANCIES[i]) for i in top_indices]


def main():
    print("Starting semantic search...")

    for _model in EMBED_MAP.keys():
        for doc in VACANCIES:
            embedded = embed(doc, embed_model=_model)
            EMBEDDED_DATA.append(embedded)
        res = search(QUERY, embed_model=_model)
        print(f"Top 3 results for '{QUERY}' using {_model}: {res}")
        EMBEDDED_DATA.clear()


if __name__ == "__main__":
    main()


