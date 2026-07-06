"""Returns a chat model based on LLM_PROVIDER, so you can switch between
free providers by changing one line in .env - no code changes needed.

Both paths below need models with reliable tool/function-calling support,
since the agent relies on it to pick the right HR tool.
"""
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import (
    LLM_PROVIDER,
    GOOGLE_API_KEY,
    GEMINI_MODEL,
    OPENROUTER_API_KEY,
    OPENROUTER_MODEL,
)


def get_llm():
    if LLM_PROVIDER == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI

        if not GOOGLE_API_KEY:
            raise RuntimeError("GOOGLE_API_KEY is not set - get a free key from Google AI Studio.")
        return ChatGoogleGenerativeAI(
            model=GEMINI_MODEL,
            google_api_key=GOOGLE_API_KEY,
            temperature=0.2,
        )

    elif LLM_PROVIDER == "openrouter":
        from langchain_openai import ChatOpenAI

        if not OPENROUTER_API_KEY:
            raise RuntimeError("OPENROUTER_API_KEY is not set - get a free key from openrouter.ai.")
        return ChatOpenAI(
            model=OPENROUTER_MODEL,
            api_key=OPENROUTER_API_KEY,
            base_url="https://openrouter.ai/api/v1",
            temperature=0.2,
        )

    else:
        raise ValueError(f"Unknown LLM_PROVIDER '{LLM_PROVIDER}'. Use 'gemini' or 'openrouter'.")
