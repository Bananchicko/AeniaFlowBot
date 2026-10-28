from aiogram import Bot
from aiogram.types import Message
from aeniaflow.core.helpers import ai_text, message_text
from aeniaflow.core.ui import answer_text


async def run(message, args, instruction):
    source = args or message_text(message)
    if not source:
        raise ValueError("Добавьте текст запроса или ответьте на сообщение.")
    await answer_text(message, await ai_text(source, system=instruction))


async def gpt(message: Message, args: str, bot: Bot):
    await run(message, args, "Ты — помощник AeniaFlow. Отвечай по-русски ясно и по делу. Не выдумывай факты.")


async def hint(message, args, bot):
    await run(
        message, args, "Дай короткую практичную подсказку. Если данных не хватает, прямо скажи об этом."
    )


async def summarize(message, args, bot):
    await run(
        message, args, "Кратко изложи основные мысли текста по-русски. Сохрани факты, не добавляй новых."
    )


async def rewrite(message, args, bot):
    await run(
        message,
        args,
        "Отредактируй текст: ясные фразы, точный смысл, без канцелярита. Верни только результат.",
    )


async def explain(message, args, bot):
    await run(message, args, "Объясни тему простыми словами и приведи один пример. Не выдумывай факты.")
