import json
from collections.abc import AsyncGenerator, Coroutine
from dataclasses import dataclass
from typing import (
    Any,
    Literal,
    TypedDict,
    overload,
)

from llm_messages_token_helper import build_messages, get_token_limit
from openai import AsyncOpenAI, AsyncStream
from openai.types.chat import (
    ChatCompletion,
    ChatCompletionChunk,
    ChatCompletionToolParam,
)

from .postgres_searcher import PostgresSearcher


def nonewlines(s: str) -> str:
    return s.replace("\n", " ").replace("\r", " ")


@dataclass
class Item:
    id: str | None
    name: str | None
    embedding: list[float] | None
    description: str | None

    def serialize_for_results(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "embedding": Item.trim_embedding(self.embedding),
            "description": self.description
        }

    @classmethod
    def trim_embedding(cls, embedding: list[float] | None) -> str | None:
        """Returns a trimmed list of floats from the vector embedding."""
        if embedding:
            if len(embedding) > 2:
                # Format the embedding list to show the first 2 items followed by the count of the remaining items."""
                return f"[{embedding[0]}, {embedding[1]} ...+{len(embedding) - 2} more]"
            else:
                return str(embedding)

        return None


@dataclass
class ThoughtStep:
    title: str
    description: Any | None
    props: dict[str, Any] | None = None



class RAGChat:
    # Chat roles
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"

    query_prompt_few_shots = [
        {"role": USER, "content": "How did crypto do last year?"},
        {"role": ASSISTANT, "content": "Summarize Cryptocurrency Market Dynamics from last year"},
        {"role": USER, "content": "What are my health plans?"},
        {"role": ASSISTANT, "content": "Show available health plans"},
    ]
    NO_RESPONSE = "0"

    query_prompt_template = """Below is a history of the conversation so far, and a new question asked by the user that needs to be answered by searching in a knowledge base.
    You have access to Azure AI Search index with 100's of documents.
    Generate a search query based on the conversation and the new question.
    Do not include cited source filenames and document names e.g info.txt or doc.pdf in the search query terms.
    Do not include any text inside [] or <<>> in the search query terms.
    Do not include any special characters like '+'.
    If the question is not in English, translate the question to English before generating the search query.
    If you cannot generate a search query, return just the number 0.
    """

    @property
    def system_message_chat_conversation(self):
        return """Assistant helps customers with questions about producs.
        Answer ONLY with the product details listed in the sources. If there isn't enough information below, say you don't know. Do not generate answers that don't use the sources below.
        For tabular information return it as an html table. Do not return markdown format. If the question is not in English, answer in the language used in the question.
        Each source has a name followed by colon and the actual information, always include the source name for each fact you use in the response. Use square brackets to reference the source, for example [info1.txt]. Don't combine sources, list each source separately, for example [info1.txt][info2.pdf].
        {injected_prompt}
        """

    def __init__(
        self,
        *,
        searcher: PostgresSearcher,
        openai_client: AsyncOpenAI,
        gpt_model: str,
        gpt_deployment: str | None,  # Not needed for non-Azure OpenAI
        embed_deployment: str | None,  # Not needed for non-Azure OpenAI or for retrieval_mode="text"
        embed_model: str,
        embed_dimensions: int
    ):
        self.searcher = searcher
        self.openai_client = openai_client
        self.gpt_model = gpt_model
        self.gpt_deployment = gpt_deployment
        self.embed_deployment = embed_deployment
        self.embed_model = embed_model
        self.embed_dimensions = embed_dimensions
        self.gpt_token_limit = get_token_limit(gpt_model)


    def get_sources_content(
        self, items: list[Item]
    ) -> list[str]:
            return [
                f"{(item.id)}:{nonewlines(item.description or '')}"
                for item in items
            ]

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

    def get_system_prompt(self, override_prompt: str | None) -> str:
        if override_prompt is None:
            return self.system_message_chat_conversation.format(
                injected_prompt=""
            )
        elif override_prompt.startswith(">>>"):
            return self.system_message_chat_conversation.format(
                injected_prompt=override_prompt[3:] + "\n"
            )
        else:
            return override_prompt

    def get_search_query(self, chat_completion: ChatCompletion, user_query: str):
        response_message = chat_completion.choices[0].message

        if response_message.tool_calls:
            for tool in response_message.tool_calls:
                if tool.type != "function":
                    continue
                function = tool.function
                if function.name == "search_sources":
                    arg = json.loads(function.arguments)
                    search_query = arg.get("search_query", self.NO_RESPONSE)
                    if search_query != self.NO_RESPONSE:
                        return search_query
        elif query_text := response_message.content:
            if query_text.strip() != self.NO_RESPONSE:
                return query_text
        return user_query

    async def run(
        self, messages: list[dict], stream: bool = False, session_state: Any = None, context: dict[str, Any] = {}
    ) -> dict[str, Any] | AsyncGenerator[dict[str, Any], None]:
        overrides = context.get("overrides", {})

        if stream is False:
            return await self.run_without_streaming(messages, overrides, session_state)
        else:
            return self.run_with_streaming(messages, overrides, session_state)

    async def run_without_streaming(
        self,
        history: list[dict[str, str]],
        overrides: dict[str, Any],
        auth_claims: dict[str, Any],
        session_state: Any = None,
    ) -> dict[str, Any]:
        extra_info, chat_coroutine = await self.run_until_final_call(
            history, overrides, auth_claims, should_stream=False
        )
        chat_completion_response: ChatCompletion = await chat_coroutine
        chat_resp = chat_completion_response.model_dump()  # Convert to dict to make it JSON serializable
        chat_resp["choices"][0]["context"] = extra_info
        chat_resp["choices"][0]["session_state"] = session_state
        return chat_resp

    async def run_with_streaming(
        self,
        history: list[dict[str, str]],
        overrides: dict[str, Any],
        auth_claims: dict[str, Any],
        session_state: Any = None,
    ) -> AsyncGenerator[dict, None]:
        extra_info, chat_coroutine = await self.run_until_final_call(
            history, overrides, auth_claims, should_stream=True
        )
        yield {
            "choices": [
                {
                    "delta": {"role": self.ASSISTANT},
                    "context": extra_info,
                    "session_state": session_state,
                    "finish_reason": None,
                    "index": 0,
                }
            ],
            "object": "chat.completion.chunk",
        }

        async for event_chunk in await chat_coroutine:
            # "2023-07-01-preview" API version has a bug where first response has empty choices
            event = event_chunk.model_dump()  # Convert pydantic model to dict
            if event["choices"]:
                yield event
    
    @overload
    async def run_until_final_call(
        self,
        history: list[dict[str, str]],
        overrides: dict[str, Any],
        auth_claims: dict[str, Any],
        should_stream: Literal[False],
    ) -> tuple[dict[str, Any], Coroutine[Any, Any, ChatCompletion]]: ...

    @overload
    async def run_until_final_call(
        self,
        history: list[dict[str, str]],
        overrides: dict[str, Any],
        auth_claims: dict[str, Any],
        should_stream: Literal[True],
    ) -> tuple[dict[str, Any], Coroutine[Any, Any, AsyncStream[ChatCompletionChunk]]]: ...

    async def run_until_final_call(
        self,
        history: list[dict[str, str]],
        overrides: dict[str, Any],
        auth_claims: dict[str, Any],
        should_stream: bool = False,
    ) -> tuple[dict[str, Any], Coroutine[Any, Any, ChatCompletion | AsyncStream[ChatCompletionChunk]]]:
        has_text = overrides.get("retrieval_mode") in ["text", "hybrid", None]
        has_vector = overrides.get("retrieval_mode") in ["vectors", "hybrid", None]
        top = overrides.get("top", 3)
        minimum_search_score = overrides.get("minimum_search_score", 0.0)
        minimum_reranker_score = overrides.get("minimum_reranker_score", 0.0)

        use_semantic_ranker = True if overrides.get("semantic_ranker") and has_text else False

        original_user_query = history[-1]["content"]
        user_query_request = "Generate search query for: " + original_user_query

        tools: list[ChatCompletionToolParam] = [
            {
                "type": "function",
                "function": {
                    "name": "search_sources",
                    "description": "Retrieve sources from the Azure AI Search index",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "search_query": {
                                "type": "string",
                                "description": "Query string to retrieve documents from azure search eg: 'Health care plan'",
                            }
                        },
                        "required": ["search_query"],
                    },
                },
            }
        ]

        # STEP 1: Generate an optimized keyword search query based on the chat history and the last question
        query_messages = build_messages(
            model=self.gpt_model,
            system_prompt=self.query_prompt_template,
            new_user_message=user_query_request,
            past_messages=history,
            few_shots=self.query_prompt_few_shots,
            max_tokens=self.gpt_token_limit - len(user_query_request),
        )

        chat_completion: ChatCompletion = await self.openai_client.chat.completions.create(
            messages=query_messages,  # type: ignore
            # Azure OpenAI takes the deployment name as the model name
            model=self.gpt_deployment if self.gpt_deployment else self.gpt_model,
            temperature=0.0,  # Minimize creativity for search query generation
            max_tokens=100,  # Setting too low risks malformed JSON, setting too high may affect performance
            n=1,
            tools=tools,
            tool_choice="auto",
        )

        query_text = self.get_search_query(chat_completion, original_user_query)

        # STEP 2: Retrieve relevant documents from the search index with the GPT optimized query

        # If retrieval mode includes vectors, compute an embedding for the query
        vector: list[float] = []
        if has_vector:
            vector = await self.compute_text_embedding(original_user_query)

        # Only keep the text query if the retrieval mode uses text, otherwise drop it
        if not has_text:
            query_text = None

        results = await self.searcher.hybrid_search(
            original_user_query,
            vector,
            top
        )

        sources_content = self.get_sources_content(results)
        content = "\n".join(sources_content)

        # STEP 3: Generate a contextual and content specific answer using the search results and chat history

        # Allow client to replace the entire prompt, or to inject into the exiting prompt using >>>
        system_message = self.get_system_prompt(overrides.get("prompt_template"),)

        response_token_limit = 1024
        messages_token_limit = self.gpt_token_limit - response_token_limit
        messages = build_messages(
            model=self.gpt_model,
            system_prompt=system_message,
            # Model does not handle lengthy system messages well. Moving sources to latest user conversation to solve follow up questions prompt.
            new_user_message=original_user_query + "\n\nSources:\n" + content,
            past_messages=history,
            max_tokens=messages_token_limit,
        )

        data_points = {"text": sources_content}

        extra_info = {
            "data_points": data_points,
            "thoughts": [
                ThoughtStep(
                    "Prompt to generate search query",
                    [str(message) for message in query_messages],
                    (
                        {"model": self.gpt_model, "deployment": self.gpt_deployment}
                        if self.gpt_deployment
                        else {"model": self.gpt_model}
                    ),
                ),
                ThoughtStep(
                    "Search using generated search query",
                    query_text,
                    {
                        "use_semantic_ranker": use_semantic_ranker,
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
