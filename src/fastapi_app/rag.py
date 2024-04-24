import pathlib
from collections.abc import AsyncGenerator, Coroutine
from dataclasses import dataclass
from typing import (
    Any,
    TypedDict,
)

from llm_messages_token_helper import build_messages, get_token_limit
from openai import AsyncOpenAI, AsyncStream
from openai.types.chat import (
    ChatCompletion,
    ChatCompletionChunk,
)

from .postgres_searcher import PostgresSearcher
from .query_rewriter import build_search_function, extract_search_arguments


@dataclass
class ThoughtStep:
    title: str
    description: Any | None
    props: dict[str, Any] | None = None


class RAGChat:

    def __init__(
        self,
        *,
        searcher: PostgresSearcher,
        openai_client: AsyncOpenAI,
        gpt_model: str,
        gpt_deployment: str | None,  # Not needed for non-Azure OpenAI
        embed_deployment: str | None,  # Not needed for non-Azure OpenAI or for retrieval_mode="text"
        embed_model: str,
        embed_dimensions: int,
    ):
        self.searcher = searcher
        self.openai_client = openai_client
        self.gpt_model = gpt_model
        self.gpt_deployment = gpt_deployment
        self.embed_deployment = embed_deployment
        self.embed_model = embed_model
        self.embed_dimensions = embed_dimensions
        self.gpt_token_limit = get_token_limit(gpt_model)
        current_dir = pathlib.Path(__file__).parent
        self.query_prompt_template = open(current_dir / "prompts/query.txt").read()
        self.answer_prompt_template = open(current_dir / "prompts/answer.txt").read()

    async def compute_text_embedding(self, q: str):
        SUPPORTED_DIMENSIONS_MODEL = {
            "text-embedding-ada-002": False,
            "text-embedding-3-small": True,
            "text-embedding-3-large": True,
        }

        class ExtraArgs(TypedDict, total=False):
            dimensions: int

        dimensions_args: ExtraArgs = (
            {"dimensions": self.embedding_dimensions} if SUPPORTED_DIMENSIONS_MODEL[self.embed_model] else {}
        )

        embedding = await self.openai_client.embeddings.create(
            # Azure OpenAI takes the deployment name as the model name
            model=self.embed_deployment if self.embed_deployment else self.embed_model,
            input=q,
            **dimensions_args,
        )
        return embedding.data[0].embedding

    async def run(
        self, messages: list[dict], stream: bool = False, context: dict[str, Any] = {}
    ) -> dict[str, Any] | AsyncGenerator[dict[str, Any], None]:
        overrides = context.get("overrides", {})

        if stream is False:
            return await self.run_without_streaming(messages, overrides)
        else:
            return self.run_with_streaming(messages, overrides)

    async def run_without_streaming(self, history: list[dict[str, str]], overrides: dict[str, Any]) -> dict[str, Any]:
        extra_info, chat_coroutine = await self.run_until_final_call(history, overrides, should_stream=False)
        chat_completion_response: ChatCompletion = await chat_coroutine
        chat_resp = chat_completion_response.model_dump()  # Convert to dict to make it JSON serializable
        chat_resp["choices"][0]["context"] = extra_info
        return chat_resp

    async def run_with_streaming(
        self,
        history: list[dict[str, str]],
        overrides: dict[str, Any],
    ) -> AsyncGenerator[dict, None]:
        extra_info, chat_coroutine = await self.run_until_final_call(history, overrides, should_stream=True)
        yield {
            "choices": [
                {
                    "delta": {"role": "assistant"},
                    "context": extra_info,
                    "finish_reason": None,
                    "index": 0,
                }
            ],
            "object": "chat.completion.chunk",
        }

        async for event_chunk in await chat_coroutine:
            event = event_chunk.model_dump()  # Convert pydantic model to dict
            if event["choices"]:
                yield event

    async def run_until_final_call(
        self,
        history: list[dict[str, str]],
        overrides: dict[str, Any],
        should_stream: bool = False,
    ) -> tuple[dict[str, Any], Coroutine[Any, Any, ChatCompletion | AsyncStream[ChatCompletionChunk]]]:
        has_text = overrides.get("retrieval_mode") in ["text", "hybrid", None]
        has_vector = overrides.get("retrieval_mode") in ["vectors", "hybrid", None]
        top = overrides.get("top", 3)

        original_user_query = history[-1]["content"]

        # Generate an optimized keyword search query based on the chat history and the last question
        query_messages = build_messages(
            model=self.gpt_model,
            system_prompt=self.query_prompt_template,
            new_user_message=original_user_query,
            past_messages=history,
            max_tokens=self.gpt_token_limit - len(original_user_query),
        )

        chat_completion: ChatCompletion = await self.openai_client.chat.completions.create(
            messages=query_messages,  # type: ignore
            # Azure OpenAI takes the deployment name as the model name
            model=self.gpt_deployment if self.gpt_deployment else self.gpt_model,
            temperature=0.0,  # Minimize creativity for search query generation
            max_tokens=500,  # Setting too low risks malformed JSON, setting too high may affect performance
            n=1,
            tools=build_search_function(),
            tool_choice="auto",
        )

        query_text, filters = extract_search_arguments(chat_completion)

        # Retrieve relevant items from the database with the GPT optimized query
        vector: list[float] = []
        if has_vector:
            vector = await self.compute_text_embedding(original_user_query)
        if not has_text:
            query_text = None

        results = await self.searcher.search(query_text, vector, top, filters)

        sources_content = [f"[{(item.id)}]:{item.to_str_for_rag()}\n\n" for item in results]
        content = "\n".join(sources_content)

        # Generate a contextual and content specific answer using the search results and chat history
        response_token_limit = 1024
        messages_token_limit = self.gpt_token_limit - response_token_limit
        messages = build_messages(
            model=self.gpt_model,
            system_prompt=overrides.get("prompt_template") or self.answer_prompt_template,
            new_user_message=original_user_query + "\n\nSources:\n" + content,
            past_messages=history,
            max_tokens=messages_token_limit,
        )

        data_points = {"text": sources_content}

        extra_info = {
            "data_points": data_points,
            "thoughts": [
                ThoughtStep(
                    "Prompt to generate search arguments",
                    [str(message) for message in query_messages],
                    (
                        {"model": self.gpt_model, "deployment": self.gpt_deployment}
                        if self.gpt_deployment
                        else {"model": self.gpt_model}
                    ),
                ),
                ThoughtStep(
                    "Search using generated search arguments",
                    query_text,
                    {
                        "top": top,
                        "has_vector": has_vector,
                    },
                ),
                ThoughtStep(
                    "Search results",
                    [result.to_dict() for result in results],
                ),
                ThoughtStep(
                    "Prompt to generate answer",
                    [str(message) for message in messages],
                    (
                        {"model": self.gpt_model, "deployment": self.gpt_deployment}
                        if self.gpt_deployment
                        else {"model": self.gpt_model}
                    ),
                ),
            ],
        }

        chat_coroutine = self.openai_client.chat.completions.create(
            # Azure OpenAI takes the deployment name as the model name
            model=self.gpt_deployment if self.gpt_deployment else self.gpt_model,
            messages=messages,
            temperature=overrides.get("temperature", 0.3),
            max_tokens=response_token_limit,
            n=1,
            stream=should_stream,
        )
        return (extra_info, chat_coroutine)
