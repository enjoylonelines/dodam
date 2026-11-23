"""Configuration switch; pending conversations keep the legacy resume contract."""
from __future__ import annotations
from app.core.config import settings

async def run_chat(*, execution_guard=None, **kwargs):
    from app.services.chat._routing import run_chat_legacy
    if settings.chat_routing_mode != "function_calling" or (kwargs.get("slot") or {}).get("pending"):
        return await run_chat_legacy(**kwargs)
    from app.services.chat.function_calling_adapter import run_function_chat
    return await run_function_chat(
        **kwargs, execution_guard=execution_guard,
        max_calls=settings.chat_function_max_calls,
        timeout_seconds=settings.chat_function_timeout_seconds,
    )
