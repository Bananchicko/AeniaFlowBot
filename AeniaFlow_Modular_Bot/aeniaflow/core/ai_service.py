"""Optional AI with per-user quotas, timeouts and closed HTTP clients."""

from __future__ import annotations
import asyncio
from contextvars import ContextVar
from datetime import datetime, timezone
from openai import AsyncOpenAI, OpenAIError
from config import settings
from aeniaflow.core.runtime import db

actor_id: ContextVar[int | None] = ContextVar("actor_id", default=None)
slots = asyncio.Semaphore(3)


class AIUnavailable(RuntimeError):
    pass


def api_key():
    return db.runtime_option("openai_api_key", settings.openai_api_key)


def model_name():
    return db.runtime_option("openai_model", settings.openai_model)


def available():
    return bool(
        db.runtime_option("ai_disabled", "0") != "1"
        and api_key()
        and api_key().lower() not in {"none", "null", "your_api_key"}
    )


def reserve():
    if not available():
        raise AIUnavailable("ИИ пока не подключён владельцем бота. Остальные функции доступны.")
    user_id = actor_id.get()
    if user_id is None:
        raise AIUnavailable("Не удалось определить пользователя запроса.")
    day = datetime.now(timezone.utc).date().isoformat()
    if not db.take_quota(user_id, day, "ai", settings.ai_daily_limit):
        raise AIUnavailable(f"Лимит ИИ: {settings.ai_daily_limit} запросов в сутки. Обновление в 00:00 UTC.")
    return user_id, day


async def text(prompt: str, system: str) -> str:
    if len(prompt) > 12000:
        raise ValueError("Запрос слишком длинный: максимум 12 000 символов.")
    user_id, day = reserve()
    try:
        async with slots:
            async with AsyncOpenAI(api_key=api_key(), timeout=45, max_retries=1) as client:
                result = await client.responses.create(
                    model=model_name(),
                    instructions=system,
                    input=prompt,
                    max_output_tokens=1200,
                    store=False,
                )
                return (
                    result.output_text or "Ответ не получен. Попробуйте переформулировать запрос."
                ).strip()
    except (OpenAIError, TimeoutError) as exc:
        db.release_quota(user_id, day, "ai")
        raise AIUnavailable("ИИ-сервис временно недоступен. Лимит за этот запрос восстановлен.") from exc


async def transcribe(path: str) -> str:
    user_id, day = reserve()
    try:
        async with slots:
            async with AsyncOpenAI(api_key=api_key(), timeout=60, max_retries=1) as client:
                with open(path, "rb") as audio:
                    result = await client.audio.transcriptions.create(model="whisper-1", file=audio)
                    return result.text or "Речь не распознана."
    except (OpenAIError, TimeoutError) as exc:
        db.release_quota(user_id, day, "ai")
        raise AIUnavailable("Распознавание сейчас недоступно. Лимит восстановлен.") from exc
