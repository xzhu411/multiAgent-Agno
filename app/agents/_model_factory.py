"""
Model factory — returns the right Agno model based on available API keys.
Prefers Anthropic if ANTHROPIC_API_KEY is set, falls back to OpenAI.
"""
from __future__ import annotations

import os
from typing import Any


def get_model() -> Any:
    """Return an Agno model instance based on available credentials."""
    if os.getenv("ANTHROPIC_API_KEY"):
        from agno.models.anthropic import Claude
        model_id = os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")
        return Claude(id=model_id)
    else:
        from agno.models.openai import OpenAIChat
        model_id = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        return OpenAIChat(id=model_id)
