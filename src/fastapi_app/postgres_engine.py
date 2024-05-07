import logging
import os

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from .postgres_models import Base

logger = logging.getLogger("fastapi_app")


async def create_postgres_engine(azure_credential):

    POSTGRES_HOST = os.environ["POSTGRES_HOST"]
    POSTGRES_USERNAME = os.environ["POSTGRES_USERNAME"]
    POSTGRES_DATABASE = os.environ["POSTGRES_DATABASE"]

    if POSTGRES_HOST.endswith(".database.azure.com"):
        logger.info("Authenticating to Azure Database for PostgreSQL using Azure Identity...")
        token = await azure_credential.get_token("https://ossrdbms-aad.database.windows.net/.default")
        POSTGRES_PASSWORD = token.token
    else:
        logger.info("Authenticating to PostgreSQL using password...")
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
        # Create all tables (and indexes) defined in this model in the database
        await conn.run_sync(Base.metadata.create_all)
        # seed

    async_session_maker = async_sessionmaker(engine, expire_on_commit=False)

    return engine, async_session_maker
