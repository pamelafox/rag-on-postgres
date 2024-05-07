import asyncio
import logging
import os

import asyncpg
from azure.identity import DefaultAzureCredential

logger = logging.getLogger("scripts")


async def assign_role_for_webapp(postgres_host, postgres_username, app_identity_name):
    if not postgres_host.endswith(".database.azure.com"):
        logger.info("This script is intended to be used with Azure Database for PostgreSQL.")
        logger.info("Please set the environment variable DBHOST to the Azure Database for PostgreSQL server hostname.")
        return

    logger.info("Authenticating to Azure Database for PostgreSQL using Azure Identity...")
    azure_credential = DefaultAzureCredential()
    token = azure_credential.get_token("https://ossrdbms-aad.database.windows.net/.default")
    conn: asyncpg.connection.Connection = await asyncpg.connect(
        database="postgres",  # You must connect to postgres database when assigning roles
        user=postgres_username,
        password=token.token,
        host=postgres_host,
    )

    # Create pgvector extension
    await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")

    identities = await conn.fetch(
        f"select * from pgaadauth_list_principals(false) WHERE rolname = '{app_identity_name}'"
    )
    if len(identities) == 1:
        logger.info(f"Found an existing PostgreSQL role for identity {app_identity_name}")
    else:
        logger.info(f"Creating a PostgreSQL role for identity {app_identity_name}")
        await conn.execute(f"SELECT * FROM pgaadauth_create_principal('{app_identity_name}', false, false)")

    logger.info(f"Granting permissions to {app_identity_name}")
    # set role to azure_pg_admin
    await conn.execute(f'GRANT USAGE ON SCHEMA public TO "{app_identity_name}"')
    await conn.execute(f'GRANT CREATE ON SCHEMA public TO "{app_identity_name}"')
    try:
        await conn.execute(f'GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO "{app_identity_name}"')
        await conn.execute(
            f"ALTER DEFAULT PRIVILEGES IN SCHEMA public "
            f'GRANT SELECT, UPDATE, INSERT, DELETE ON TABLES TO "{app_identity_name}"'
        )
    except asyncpg.exceptions.InsufficientPrivilegeError:
        logger.info(
            f"Failed to grant ALL PRIVILEGES to {app_identity_name}. "
            f"Please make sure the user has the necessary permissions."
        )

    await conn.close()


async def main():
    logging.basicConfig(level=logging.WARNING)
    logger.setLevel(logging.INFO)

    POSTGRES_HOST = os.getenv("POSTGRES_HOST")
    POSTGRES_USERNAME = os.getenv("POSTGRES_USERNAME")
    APP_IDENTITY_NAME = os.getenv("SERVICE_WEB_IDENTITY_NAME")
    if not POSTGRES_HOST or not POSTGRES_USERNAME or not APP_IDENTITY_NAME:
        logger.error(
            "Can't find POSTGRES_HOST, POSTGRES_USERNAME, and SERVICE_WEB_IDENTITY_NAME environment variables. "
            "Make sure you run azd up first."
        )
    else:
        await assign_role_for_webapp(POSTGRES_HOST, POSTGRES_USERNAME, APP_IDENTITY_NAME)


if __name__ == "__main__":
    asyncio.run(main())
