from openai import OpenAI
from sentence_transformers import SentenceTransformer
from voyageai import Client
import numpy as np
from settings import settings
from constants import VACANCIES, QUERY


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
    top_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[
        :top_k
    ]
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
