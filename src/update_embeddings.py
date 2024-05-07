
import asyncio

from dotenv import load_dotenv
from sqlalchemy import select

from fastapi_app.embeddings import compute_text_embedding
from fastapi_app.openai_clients import create_openai_embed_client
from fastapi_app.postgres_engine import create_postgres_engine
from fastapi_app.postgres_models import Item


async def update_embeddings():
    engine, async_session_maker = await create_postgres_engine()
    openai_embed_client, openai_embed_model, openai_embed_dimensions = await create_openai_embed_client()

    async with async_session_maker() as session:
        async with session.begin():
            items = (await session.scalars(select(Item))).all()

            for item in items:
                item.embedding = await compute_text_embedding(
                    item.to_str_for_embedding(),
                    openai_client=openai_embed_client,
                    embed_model=openai_embed_model,
                    embedding_dimensions=openai_embed_dimensions)

            await session.commit()

if __name__ == "__main__":
    load_dotenv(override=True)
    asyncio.run(update_embeddings())