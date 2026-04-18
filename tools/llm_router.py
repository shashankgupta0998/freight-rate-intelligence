"""LLM router — single entry point for all agent LLM calls.

get_llm() returns a LangChain ChatLiteLLM configured with a LiteLLM Router
that falls back Groq -> OpenAI -> Gemini on RateLimitError / provider
outages. All agents import get_llm() — never instantiate ChatGroq,
ChatOpenAI, or ChatGoogleGenerativeAI directly (see CLAUDE.md Prohibited
patterns).
"""
from __future__ import annotations

import os
from functools import lru_cache

from dotenv import load_dotenv
from langchain_litellm import ChatLiteLLM
from litellm import Router

load_dotenv()

_MODEL_LIST = [
    {
        "model_name": "groq",
        "litellm_params": {
            "model": "groq/llama-3.3-70b-versatile",
            "api_key": os.getenv("GROQ_API_KEY"),
        },
    },
    {
        "model_name": "openai",
        "litellm_params": {
            "model": "openai/gpt-4o-mini",
            "api_key": os.getenv("OPENAI_API_KEY"),
        },
    },
    {
        "model_name": "gemini",
        "litellm_params": {
            "model": "gemini/gemini-1.5-flash",
            "api_key": os.getenv("GEMINI_API_KEY"),
        },
    },
]


@lru_cache(maxsize=1)
def get_llm(temperature: float = 0.2):
    """Return a LangChain ChatLiteLLM singleton.

    LiteLLM Router handles provider selection + fallback on RateLimitError.
    Cached so every AgentExecutor shares one underlying client.
    """
    _router = Router(
        model_list=_MODEL_LIST,
        fallbacks=[
            {"groq": ["openai", "gemini"]},
            {"openai": ["gemini"]},
        ],
        cooldown_time=60,
    )
    return ChatLiteLLM(
        model="groq/llama-3.3-70b-versatile",
        temperature=temperature,
        router=_router,
    )
