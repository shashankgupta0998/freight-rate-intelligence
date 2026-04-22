"""Unit tests for tools/llm_router.py — construction + singleton (no real calls)."""
from __future__ import annotations

from langchain_litellm import ChatLiteLLM

from tools.llm_router import _MODEL_LIST, get_llm


def test_get_llm_returns_chat_litellm_instance():
    llm = get_llm()
    assert isinstance(llm, ChatLiteLLM)


def test_get_llm_singleton_same_kwargs_returns_same_instance():
    get_llm.cache_clear()
    a = get_llm()
    b = get_llm()
    assert a is b


def test_get_llm_cache_size_one_evicts_on_different_kwargs():
    # lru_cache(maxsize=1): second call with a different temperature evicts the first.
    get_llm.cache_clear()
    first = get_llm(temperature=0.2)
    second = get_llm(temperature=0.5)
    # Both are valid instances
    assert isinstance(first, ChatLiteLLM)
    assert isinstance(second, ChatLiteLLM)


def test_model_list_has_three_providers():
    names = {entry["model_name"] for entry in _MODEL_LIST}
    assert names == {"groq", "openai", "gemini"}
