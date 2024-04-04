from __future__ import annotations

import contextlib
import json
import logging
import os

import azure.identity.aio
import fastapi
import openai
import sqlalchemy.exc
from azure.identity import DefaultAzureCredential
from environs import Env
from sqlalchemy import Index, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from .globals import global_storage
from .models import Base, Item


def create_index(conn):
    # Define HNSW index to support vector similarity search through the vector_cosine_ops access method (cosine distance). The SQL operator for cosine distance is written as <=>.
    index = Index(
        "hnsw_index_for_cosine_distance_similarity_search",
        Item.embedding,
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )

    # Create the HNSW index
    index.drop(conn, checkfirst=True)
    index.create(conn)


@contextlib.asynccontextmanager
async def lifespan(app: fastapi.FastAPI):
    # setup db engine

    POSTGRES_HOST = os.environ["POSTGRES_HOST"]
    POSTGRES_USERNAME = os.environ["POSTGRES_USERNAME"]
    POSTGRES_DATABASE = os.environ["POSTGRES_DATABASE"]

    if POSTGRES_HOST.endswith(".database.azure.com"):
        print("Authenticating to Azure Database for PostgreSQL using Azure Identity...")
        azure_credential = DefaultAzureCredential()
        token = azure_credential.get_token("https://ossrdbms-aad.database.windows.net/.default")
        POSTGRES_PASSWORD = token.token
    else:
        POSTGRES_PASSWORD = os.environ["POSTGRES_PASSWORD"]

    DATABASE_URI = f"postgresql+asyncpg://{POSTGRES_USERNAME}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}/{POSTGRES_DATABASE}"
    # Specify SSL mode if needed
    if POSTGRES_SSL := os.environ.get("POSTGRES_SSL"):
        DATABASE_URI += f"?ssl={POSTGRES_SSL}"

    engine = create_async_engine(
        DATABASE_URI,
        echo=False,
    )
    async with engine.begin() as conn:
        # Create pgvector extension
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        # Create all tables defined in this model in the database
        await conn.run_sync(Base.metadata.create_all)

        # Create the HNSW index
        await conn.run_sync(create_index)

    async_session_maker = async_sessionmaker(engine, expire_on_commit=False)

    async with async_session_maker() as session:
        # Insert the items from the JSON file
        # get path of this file using pathlib
        current_dir = os.path.dirname(os.path.realpath(__file__))
        with open(os.path.join(current_dir, "catalog.json")) as f:
            catalog_items = json.load(f)
            for catalog_item in catalog_items:

                item = Item(
                    id=catalog_item["Id"],
                    type=catalog_item["Type"],
                    brand=catalog_item["Brand"],
                    name=catalog_item["Name"],
                    description=catalog_item["Description"],
                    price=catalog_item["Price"],
                    embedding=catalog_item["Embedding"],
                )
                session.add(item)
            try:
                await session.commit()
            except sqlalchemy.exc.IntegrityError:
                pass
    global_storage.engine = engine
    global_storage.async_session_maker = async_session_maker

    OPENAI_API_HOST = os.getenv("OPENAI_API_HOST")
    if OPENAI_API_HOST == "azure":
        token_provider = azure.identity.get_bearer_token_provider(
            azure.identity.DefaultAzureCredential(), "https://cognitiveservices.azure.com/.default"
        )
        global_storage.openai_client = openai.AsyncAzureOpenAI(
            api_version=os.getenv("AZURE_OPENAI_VERSION"),
            azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
            azure_ad_token_provider=token_provider,
        )
        global_storage.openai_gpt_model = os.getenv("AZURE_OPENAI_GPT_MODEL")
        global_storage.openai_gpt_deployment = os.getenv("AZURE_OPENAI_GPT_DEPLOYMENT")
        global_storage.openai_embed_model = os.getenv("AZURE_OPENAI_EMBED_MODEL")
        global_storage.openai_embed_deployment = os.getenv("AZURE_OPENAI_EMBED_DEPLOYMENT")
    elif OPENAI_API_HOST == "ollama":
        global_storage.openai_client = openai.AsyncOpenAI(
            base_url=os.getenv("OLLAMA_ENDPOINT"),
            api_key="nokeyneeded",
        )
        global_storage.openai_gpt_model = os.getenv("OLLAMA_GPT_MODEL")
    else:
        global_storage.openai_client = openai.AsyncOpenAI(api_key=os.getenv("OPENAICOM_KEY"))
        global_storage.openai_gpt_model = os.getenv("OPENAICOM_GPT_MODEL")
        global_storage.openai_embed_model = os.getenv("OPENAICOM_EMBED_MODEL")

    yield


def create_app():
    env = Env()

    if not os.getenv("RUNNING_IN_PRODUCTION"):
        env.read_env(".env")
        logging.basicConfig(level=logging.DEBUG)

    app = fastapi.FastAPI(docs_url="/", lifespan=lifespan)

    from . import routes  # noqa

    app.include_router(routes.router)

    return app


app = create_app()
