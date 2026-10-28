from __future__ import annotations
import asyncio
import json
import time
from datetime import datetime, timezone
from html import escape, unescape
from pathlib import Path
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from aiogram.types import Message, FSInputFile, InputMediaPhoto
from config import BASE_DIR
from aiogram.exceptions import TelegramBadRequest, TelegramAPIError
from aeniaflow.core.runtime import BoundedCache


def format_time(stamp: int, zone: str = "UTC") -> str:
    try:
        tz = ZoneInfo(zone)
    except (ZoneInfoNotFoundError, ValueError):
        tz = timezone.utc
        zone = "UTC"
    return escape(datetime.fromtimestamp(stamp, tz).strftime("%d.%m.%Y %H:%M") + " · " + zone)


async def answer_text(message: Message, text: str, *, escaped: bool = True):
    """Send readable text results within Telegram message limits."""
    from aeniaflow.core.responses import respond

    return await respond(message, escape(text) if escaped else text, parse_mode="HTML" if escaped else None)


def private_owner(message: Message, user=None, *, allow_disconnected=False) -> bool:
    """Both supported private contexts belong to the human actor, not a bot sender."""
    from aeniaflow.core.runtime import db

    actor = user or message.from_user
    if message.chat.type != "private" or not actor or actor.is_bot:
        return False
    connection_id = getattr(message, "business_connection_id", None)
    if not connection_id:
        return message.chat.id == actor.id
    from aeniaflow.core.business_access import human_dialog

    if not human_dialog(message):
        return False
    connection = db.connection_owner(connection_id)
    return bool(
        connection
        and connection["owner_id"] == actor.id
        and (allow_disconnected or connection["is_enabled"] and connection["can_reply"])
    )


async def private_only(message: Message, user=None) -> bool:
    if private_owner(message, user):
        return True
    await message.answer("Действие доступно владельцу в личном чате с ботом или подключённом ЛС.")
    return False


# Telegram file IDs avoid uploading the same banner on every button click.
photo_ids = {}
panels = BoundedCache(limit=2048)
panel_locks = [asyncio.Lock() for _ in range(64)]


async def panel(
    message,
    text,
    reply_markup=None,
    *,
    edit=False,
    protect_content=False,
    art="home",
    _page=0,
    admin_only=False,
    fresh=False,
):
    """Keep one active menu in each bot DM or connected conversation."""
    from aeniaflow.core.runtime import db
    from aeniaflow.core.legal_pages import split_pages
    from aeniaflow.keyboards import kb
    from aiogram.types import InlineKeyboardMarkup

    key = (message.bot.id, message.business_connection_id, message.chat.id)
    async with panel_locks[hash(key) % len(panel_locks)]:
        bot = message.bot
        original = message
        rows = list(reply_markup.inline_keyboard) if reply_markup else []
        markup = InlineKeyboardMarkup(inline_keyboard=rows)
        payload = {
            "text": text,
            "markup": markup.model_dump(mode="json", exclude_none=True),
            "art": art or "home",
            "protected": protect_content,
            "admin_only": admin_only,
        }
        rendered = unescape(re.sub(r"<[^>]+>", "", text))
        if len(rendered.encode("utf-16-le")) // 2 > 990:
            pages = split_pages(rendered, limit=850)
            page = max(0, min(_page, len(pages) - 1))
            text = escape(pages[page]) + f"\n\n{page+1} / {len(pages)}"
            rows = (
                kb(
                    [
                        [
                            ("‹", f"panelpage:{page-1}" if page else "nav:first"),
                            ("›", f"panelpage:{page+1}" if page + 1 < len(pages) else "nav:last"),
                        ]
                    ]
                ).inline_keyboard
                + rows
            )
            markup = InlineKeyboardMarkup(inline_keyboard=rows)
        cached = panels.get(key)
        if not cached:
            saved = db.load_panel(*key)
            if saved:
                try:
                    cached = (time.monotonic(), Message.model_validate_json(saved["message"]).as_(bot))
                except (ValueError, TypeError):
                    cached = None
        if cached and fresh:
            old = cached[1].as_(bot)
            try:
                if old.business_connection_id:
                    await bot.delete_business_messages(
                        business_connection_id=old.business_connection_id, message_ids=[old.message_id]
                    )
                else:
                    await old.delete()
            except TelegramAPIError:
                try:
                    await old.edit_reply_markup(reply_markup=None)
                except TelegramAPIError:
                    pass
            panels.pop(key, None)
            db.conn.execute(
                "DELETE FROM ui_panels WHERE bot_id=? AND connection_id=? AND chat_id=?",
                (key[0], key[1] or "", key[2]),
            )
            cached = None
            message, edit = original, False
        if cached:
            message, edit = cached[1].as_(bot), True
        try:
            result = await _panel(
                message, text, markup, edit=edit, protect_content=protect_content, art=art or "home"
            )
        except TelegramBadRequest as exc:
            if not any(
                token in exc.message.lower()
                for token in (
                    "wrong file identifier",
                    "file_id_invalid",
                    "file reference expired",
                    "file_reference_expired",
                )
            ):
                raise
            photo_ids.pop((bot.id, art or "home"), None)
            result = await _panel(
                message, text, markup, edit=edit, protect_content=protect_content, art=art or "home"
            )
        if isinstance(result, Message):
            # Telegram's edit response may omit the Business connection in some clients.
            result = result.model_copy(update={"business_connection_id": original.business_connection_id})
            panels[key] = (time.monotonic(), result.as_(bot))
            db.save_panel(*key, result.model_dump_json(exclude_none=True), payload)
        return result


async def panel_page(message, page):
    from aeniaflow.core.runtime import db
    from aiogram.types import InlineKeyboardMarkup

    saved = db.load_panel(message.bot.id, message.business_connection_id, message.chat.id)
    if not saved:
        return
    payload = json.loads(saved["pages"])
    if payload.get("admin_only"):
        from aeniaflow.core.access import is_owner

        if message.business_connection_id or not is_owner(message.chat.id):
            return
    if payload:
        await panel(
            message,
            payload["text"],
            InlineKeyboardMarkup.model_validate(payload["markup"]),
            edit=True,
            art=payload["art"],
            protect_content=payload["protected"],
            _page=page,
            admin_only=payload.get("admin_only", False),
        )


async def _panel(message, text, reply_markup=None, *, edit=False, protect_content=False, art="home"):
    """Short panels are photo + caption + real inline controls. Long records stay readable."""
    rendered = unescape(re.sub(r"<[^>]+>", "", text))
    # Telegram counts UTF-16 code units for caption limits.
    illustrated = bool(art and len(rendered.encode("utf-16-le")) // 2 <= 1024)
    key = (message.bot.id, art)
    if illustrated:
        if art not in {"home", "dialogs", "plus", "connect"}:
            raise ValueError("Неизвестная обложка.")
        path = Path(BASE_DIR) / "assets" / f"{art}.png"
        illustrated = bool(photo_ids.get(key) or path.is_file())
        source = photo_ids.get(key) or FSInputFile(path)
    if edit:
        try:
            if illustrated:
                result = await message.edit_media(
                    InputMediaPhoto(media=source, caption=text, parse_mode="HTML"), reply_markup=reply_markup
                )
                if isinstance(result, Message) and result.photo:
                    photo_ids[key] = result.photo[-1].file_id
                return result
            if message.text is not None:
                return await message.edit_text(text, reply_markup=reply_markup, parse_mode="HTML")
        except TelegramBadRequest as exc:
            if "message is not modified" in exc.message.lower():
                return message
            if not any(
                s in exc.message.lower()
                for s in (
                    "can't be edited",
                    "not found",
                    "no text",
                    "no media",
                    "message_id_invalid",
                    "message_to_edit_not_found",
                )
            ):
                raise
    if illustrated:
        result = await message.answer_photo(
            source,
            caption=text,
            reply_markup=reply_markup,
            parse_mode="HTML",
            protect_content=protect_content,
        )
        if result.photo:
            photo_ids[key] = result.photo[-1].file_id
    else:
        result = await message.answer(
            text, reply_markup=reply_markup, parse_mode="HTML", protect_content=protect_content
        )
    if edit:
        try:
            if message.business_connection_id:
                await message.bot.delete_business_messages(
                    business_connection_id=message.business_connection_id, message_ids=[message.message_id]
                )
            else:
                await message.delete()
        except TelegramAPIError:
            try:
                await message.edit_reply_markup(reply_markup=None)
            except TelegramAPIError:
                pass
    return result
