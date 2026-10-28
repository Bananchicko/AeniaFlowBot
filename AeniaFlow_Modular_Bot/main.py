from __future__ import annotations
import asyncio
import contextlib
import logging
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError
from aiogram.types import BotCommand, BotCommandScopeChat, BotCommandScopeAllPrivateChats
from aeniaflow import __version__

try:
    from config import settings
except ValueError as exc:
    # Settings are constructed during import, before the async entry point starts.
    if __name__ == "__main__":
        raise SystemExit(f"Ошибка настройки: {exc}") from None
    raise
from aeniaflow.core.runtime import db
from aeniaflow.core.scheduling import reminder_worker
from aeniaflow.core.delivery import delivery_worker
from aeniaflow.core.telegram_errors import redact
from aeniaflow.core.access import admin_ids
from aeniaflow.handlers.system.command_dispatcher import router as command_router
from aeniaflow.handlers.system.callbacks import router as callback_router
from aeniaflow.handlers.system.payments import router as payments_router
from aeniaflow.handlers.system.business import router as business_router


class RedactCredentials(logging.Filter):
    def filter(self, record):
        record.msg, record.args = redact(record.getMessage()), ()
        if record.exc_info:
            record.exc_text = redact(logging.Formatter().formatException(record.exc_info))
            record.exc_info = None
        elif record.exc_text:
            record.exc_text = redact(record.exc_text)
        return True


def build_dispatcher() -> Dispatcher:
    dispatcher = Dispatcher()
    # Specific service-message handlers MUST run before the catch-all command router.
    dispatcher.include_router(payments_router)
    dispatcher.include_router(callback_router)
    dispatcher.include_router(business_router)
    dispatcher.include_router(command_router)
    return dispatcher


async def main():
    settings.validate()
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    for handler in logging.getLogger().handlers:
        handler.addFilter(RedactCredentials())
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)
    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    worker = None
    deliveries = None
    try:
        db.conn.execute("SELECT 1")
        dp = build_dispatcher()
        # The Telegram service menu cannot contain dot-prefixed commands.
        await bot.delete_my_commands()
        await bot.set_my_commands(
            [
                BotCommand(command="start", description="Открыть меню · команды через точку"),
                BotCommand(command="paysupport", description="Поддержка платежей"),
            ],
            scope=BotCommandScopeAllPrivateChats(),
        )
        for owner in admin_ids():
            try:
                await bot.delete_my_commands(scope=BotCommandScopeChat(chat_id=owner))
            except TelegramAPIError:
                logging.getLogger("aeniaflow").warning("Admin menu unavailable for %s", owner)
        await bot.delete_webhook(drop_pending_updates=False)
        me = await bot.get_me()
        logging.getLogger("aeniaflow").info("AeniaFlow %s started: @%s", __version__, me.username)
        worker = asyncio.create_task(reminder_worker(bot), name="durable-reminders")
        deliveries = asyncio.create_task(delivery_worker(bot), name="delivery-queues")
        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types(),
            tasks_concurrency_limit=32,
            close_bot_session=False,
        )
    finally:
        if deliveries:
            deliveries.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await deliveries
        if worker:
            worker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await worker
        db.close()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    except ValueError as exc:
        raise SystemExit(str(exc)) from None
