import json
import dataclasses
import os

import fastapi
from pydantic import BaseModel

from .globals import global_storage
from .postgres_searcher import PostgresSearcher
from .rag import RAGChat

router = fastapi.APIRouter()



class Message(BaseModel):
    content: str
    role: str = "user"


class ChatRequest(BaseModel):
    messages: list[Message]
    stream: bool = True



class JSONEncoder(json.JSONEncoder):
    def default(self, o):
        if dataclasses.is_dataclass(o):
            return dataclasses.asdict(o)
        return super().default(o)


@router.post("/chat")
async def chat_handler(chat_request: ChatRequest):
    ragchat = RAGChat(
        searcher=PostgresSearcher(global_storage.async_session_maker),
        openai_client=global_storage.openai_client,
        gpt_model=global_storage.openai_gpt_model,
        gpt_deployment=global_storage.openai_gpt_deployment,
        embed_deployment=global_storage.openai_embed_deployment,
        embed_model=global_storage.openai_embed_model,
        embed_dimensions=global_storage.openai_embed_dimensions,
    )
    messages = [message.model_dump() for message in chat_request.messages]
    context={"overrides": {"retrieval_mode": "hybrid"}}
    if chat_request.stream:
        async def response_stream():
            chat_coroutine = ragchat.run(messages, stream=True, context=context)
            # todo try except
            async for event in await chat_coroutine:
                yield json.dumps(event, ensure_ascii=False, cls=JSONEncoder) + "\n"
        return fastapi.responses.StreamingResponse(response_stream())
    else:
        response = await ragchat.run(messages, stream=False, context=context)
        return response
