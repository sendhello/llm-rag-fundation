import asyncio

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Index,
    Text,
    insert,
    select,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
)
from voyageai import Client

from constants import QUERY, VACANCIES
from settings import settings

engine = create_async_engine(str(settings.pg_dsn), echo=False, future=True)
async_session = async_sessionmaker(engine, expire_on_commit=False)
embedding_client = Client(api_key=settings.voyage_api_key)


async def get_session() -> AsyncSession:
    async with async_session() as session:
        yield session


async def create_database() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def purge_database() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


def embed(text: str) -> list[float]:
    return embedding_client.embed([text], model="voyage-4-large").embeddings[0]


class Base(DeclarativeBase):
    pass


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(Vector(1024))
    doc_metadata: Mapped[dict] = mapped_column(JSONB)

    __table_args__ = (
        Index(
            "embedding_vector_idx",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
            postgresql_with={"m": 16, "ef_construction": 64},
        ),
    )


async def bulk_insert_documents(
    session: AsyncSession, documents: list[tuple[str, list[float]]]
) -> None:
    stmt = insert(Document).values(
        [
            {"content": doc[0], "embedding": doc[1], "doc_metadata": {}}
            for doc in documents
        ]
    )
    await session.execute(stmt)
    await session.commit()


async def search_similar(
    session: AsyncSession, query_embedding: list[float], top_k: int = 3
) -> list[tuple[Document, float]]:
    distance = Document.embedding.cosine_distance(query_embedding)
    stmt = (
        select(Document, (1 - distance).label("similarity"))
        .order_by(distance)
        .limit(top_k)
    )
    results = await session.execute(stmt)
    return [(row.Document, row.similarity) for row in results]


async def put_data():
    embedded_data: list[tuple[str, list[float]]] = []
    for doc in VACANCIES:
        embedded = embed(doc)
        embedded_data.append((doc, embedded))

    await bulk_insert_documents(async_session(), embedded_data)


async def main():
    await purge_database()
    await create_database()
    print("Database created and ready for use.")

    await put_data()
    print("Data inserted successfully.")

    print("Starting semantic search...")
    async with async_session() as session:
        query_embedding = embed(QUERY)
        results = await search_similar(session, query_embedding, top_k=3)
        print("Top 3 similar documents:")
        for doc, similarity in results:
            print(f"Similarity: {similarity:.4f}, Content: {doc.content}")


if __name__ == "__main__":
    asyncio.run(main())
