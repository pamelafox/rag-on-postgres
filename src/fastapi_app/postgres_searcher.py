from pgvector.utils import to_db
from sqlalchemy import Float, Integer, select, text

from .models import Item


class PostgresSearcher:

    def __init__(self, async_session_maker):
        self.async_session_maker = async_session_maker

    async def search(
        self,
        query_text: str | None,
        query_vector: list[float] | None,
        query_top: int = 5,
        filters: list[dict] | None = None,
    ):
        filter_clause_where = ""
        filter_clause_and = ""
        if filters is not None and len(filters) > 0:
            filter = filters[0]
            filter_clause = f"{filter['column']} {filter['comparison_operator']} {filter['value']}"
            filter_clause_where = f"WHERE {filter_clause}"
            filter_clause_and = f"AND {filter_clause}"

        query_template = f"""
        WITH semantic_search AS (
            SELECT id, RANK () OVER (ORDER BY embedding <=> :embedding) AS rank
            FROM items
            {filter_clause_where}
            ORDER BY embedding <=> :embedding
            LIMIT 20
        ),
        keyword_search AS (
            SELECT id, RANK () OVER (ORDER BY ts_rank_cd(to_tsvector('english', description), query) DESC)
            FROM items, plainto_tsquery('english', :query) query
            WHERE to_tsvector('english', description) @@ query {filter_clause_and}
            ORDER BY ts_rank_cd(to_tsvector('english', description), query) DESC
            LIMIT 20
        )
        SELECT
            COALESCE(semantic_search.id, keyword_search.id) AS id,
            COALESCE(1.0 / (:k + semantic_search.rank), 0.0) +
            COALESCE(1.0 / (:k + keyword_search.rank), 0.0) AS score
        FROM semantic_search
        FULL OUTER JOIN keyword_search ON semantic_search.id = keyword_search.id
        ORDER BY score DESC
        LIMIT :limit
        """

        sql = text(query_template).columns(id=Integer, score=Float)

        async with self.async_session_maker() as session:
            results = (
                await session.execute(
                    sql,
                    {"embedding": to_db(query_vector), "query": query_text, "k": 60, "limit": query_top},
                )
            ).fetchall()

            # Convert results to Item models
            items = []
            for id, _ in results:
                item = await session.execute(select(Item).where(Item.id == id))
                items.append(item.scalar())
            return items
