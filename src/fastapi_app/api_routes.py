import fastapi

from .api_models import ChatRequest
from .globals import global_storage
from .postgres_searcher import PostgresSearcher
from .rag_advanced import AdvancedRAGChat

router = fastapi.APIRouter()


@router.post("/chat")
async def chat_handler(chat_request: ChatRequest):
    ragchat = AdvancedRAGChat(
        searcher=PostgresSearcher(global_storage.engine),
        openai_chat_client=global_storage.openai_chat_client,
        chat_model=global_storage.openai_chat_model,
        chat_deployment=global_storage.openai_chat_deployment,
        openai_embed_client=global_storage.openai_embed_client,
        embed_deployment=global_storage.openai_embed_deployment,
        embed_model=global_storage.openai_embed_model,
        embed_dimensions=global_storage.openai_embed_dimensions,
    )

    messages = [message.model_dump() for message in chat_request.messages]
    overrides = chat_request.context.get("overrides", {})
    response = await ragchat.run(messages, overrides=overrides)
    return response
