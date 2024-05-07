
import asyncio
import json
import os

import sqlalchemy.exc
from dotenv import load_dotenv
from sqlalchemy import select

from fastapi_app.postgres_engine import create_postgres_engine
from fastapi_app.postgres_models import Item


async def seed_data():
    engine, async_session_maker = await create_postgres_engine()

    async with async_session_maker() as session:
        # Insert the items from the JSON file into the database
        current_dir = os.path.dirname(os.path.realpath(__file__))
        with open(os.path.join(current_dir, "seed_data.json")) as f:
            catalog_items = json.load(f)
            for catalog_item in catalog_items:
                # check if item already exists
                item = await session.execute(select(Item).filter(Item.id == catalog_item["Id"]))
                if item.scalars().first():
                    continue
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

if __name__ == "__main__":
    load_dotenv(override=True)
    asyncio.run(seed_data())