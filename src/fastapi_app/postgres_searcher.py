
import asyncio
import logging

from sqlalchemy import select

from .models import Item


class PostgresSearcher:

    def __init__(self, async_session_maker):
        self.async_session_maker = async_session_maker
        
    async def vector_search(self, session, query_vector: list[float] | None):
        if query_vector is None or len(query_vector) == 0:
            return []
        # for embeddings: recommendation is to concatenate all the text-y columns into a single string with colons (up to token limit)
        #  compute an embedding and store in single column
        # keep the function in source control that computed the embeddings
        # Name: Red Shoe
        # Description: A shoe that is red
        # Category: Shoes
        # Or we also show how to query on multiple embeddings and combine results
        # *Dont* include columns like price in the embedding
        return await session.scalars(select(Item).order_by(Item.embedding.cosine_distance(query_vector)).limit(5))


    async def keyword_search(self, session, query_text: str | None):
        # todo index for keyword search
        if query_text is None:
            return []
        # TODO: use tsvector/tsrank - full text search
        # you may want to search across multiple columns
        return await session.scalars(select(Item).where(Item.name.ilike(f"%{query_text}%")).limit(5))

    async def hybrid_search(self, query_text: str | None, query_vector: list[float] | None, query_top: int = 5):
        logging.info(f"Hybrid search: {query_text=} {query_vector=}")
        async with self.async_session_maker() as session:
            results = await asyncio.gather(
                self.vector_search(session, query_vector),
                self.keyword_search(session, query_text),
            )
            logging.info(f"Hybrid search results: {results=}")
            # de-duplicate results
            matching_items = []
            for items in results:
                for item in items:
                    if item not in matching_items:
                        matching_items.append(item)
            # todo: rerank
            # either/and
            # do RRF (Rank Reciprocal Fusion)
            # or model

            return matching_items[0 : query_top]

