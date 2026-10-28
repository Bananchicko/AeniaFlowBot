from __future__ import annotations
import os
import itertools
from pathlib import Path
from datetime import datetime, timezone
from types import SimpleNamespace
import pytest
from dotenv import dotenv_values

# Never load the owner's shipped .env into tests or their child processes.
_project = Path(__file__).resolve().parents[1]
for _name in dotenv_values(_project / ".env.example"):
    os.environ.pop(_name, None)
os.environ["AENIA_ENV_FILE"] = str(_project / "tests" / "fixtures" / "empty.env")

from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.types import Message, User, Update, ChatMemberMember, BusinessConnection
from aeniaflow.core.database import Database
from aeniaflow.core.runtime import db, command_seen
from main import build_dispatcher


class RecordingSession(BaseSession):
    def __init__(self):
        super().__init__()
        self.requests = []
        self.member_ids = []
        self.counter = itertools.count(100)
        self.connections = {}

    async def close(self):
        pass

    async def make_request(self, bot, method, timeout=None):
        self.requests.append(method)
        name = method.__api_method__
        if name == "getMe":
            return User(id=123456, is_bot=True, first_name="AeniaFlow", username="AeniaFlowTestBot")
        if name == "getBusinessConnection":
            return BusinessConnection.model_validate(self.connections[method.business_connection_id])
        if name == "getChatMember":
            self.member_ids.append(method.user_id)
            return ChatMemberMember(user=User(id=method.user_id, is_bot=False, first_name="Member"))
        if name.startswith(("answer", "delete", "restrict", "ban", "unban", "refund", "set")) or name in {
            "editMessageReplyMarkup",
            "readBusinessMessage",
        }:
            return True
        if name.startswith(("send", "edit")):
            chat = int(method.chat_id)
            return Message(
                message_id=getattr(method, "message_id", None) or next(self.counter),
                date=datetime.now(timezone.utc),
                chat={"id": chat, "type": "private" if chat > 0 else "supergroup"},
                from_user={"id": 123456, "is_bot": True, "first_name": "AeniaFlow"},
                text=getattr(method, "text", None),
                caption=getattr(getattr(method, "media", None), "caption", None)
                or getattr(method, "caption", None),
                photo=(
                    [{"file_id": "cached-cover", "file_unique_id": "cover", "width": 1774, "height": 887}]
                    if name in {"sendPhoto", "editMessageMedia"}
                    else None
                ),
                business_connection_id=getattr(method, "business_connection_id", None),
            )
        raise AssertionError(f"Unexpected API request: {name}")

    async def stream_content(self, *args, **kwargs):
        if False:
            yield b""


@pytest.fixture(autouse=True)
def repository(tmp_path):
    old = db.instance
    db.instance = Database(str(tmp_path / "test.sqlite3"))
    from aeniaflow.core.inputs import recent_media, pending_inputs

    recent_media.clear()
    pending_inputs.clear()
    command_seen.clear()
    from aeniaflow.core.ui import photo_ids, panels
    from aeniaflow.core.runtime import processed_messages, business_notices
    from aeniaflow.handlers.commands.message_series import active, drafts

    photo_ids.clear()
    panels.clear()
    processed_messages.clear()
    business_notices.clear()
    active.clear()
    drafts.clear()
    yield db.instance
    db.instance.close()
    db.instance = old


@pytest.fixture(scope="session")
def dispatcher():
    return build_dispatcher()


@pytest.fixture
async def client(dispatcher):
    session = RecordingSession()
    bot = Bot("123456:" + "A" * 35, session=session)
    ids = itertools.count(1)

    def message(user_id=42, chat_id=None, **extra):
        chat_id = user_id if chat_id is None else chat_id
        return {
            "message_id": next(ids),
            "date": int(datetime.now(timezone.utc).timestamp()),
            "chat": {"id": chat_id, "type": "private" if chat_id > 0 else "supergroup"},
            "from": {"id": user_id, "is_bot": False, "first_name": "Alice <&>", "username": "alice"},
            **extra,
        }

    async def feed(**payload):
        await dispatcher.feed_update(bot, Update.model_validate({"update_id": next(ids), **payload}))

    async def send(text, user_id=42, chat_id=None):
        await feed(message=message(user_id, chat_id, text=text))

    async def callback(
        data, user_id=42, chat_id=None, mid=1, illustrated=False, business=None, verified_human=False
    ):
        if business and verified_human:
            db.remember_peer(User(id=chat_id or user_id, is_bot=False, first_name="Peer"))
        raw = message(user_id, chat_id, text="Menu")
        if business:
            raw["business_connection_id"] = business
        if illustrated:
            raw.pop("text", None)
            raw["photo"] = [{"file_id": "menu-art", "file_unique_id": "cover", "width": 1774, "height": 887}]
        raw["from"] = {"id": 123456, "is_bot": True, "first_name": "AeniaFlow"}
        raw["message_id"] = mid
        await feed(
            callback_query={
                "id": str(next(ids)),
                "from": {"id": user_id, "is_bot": False, "first_name": "Alice"},
                "chat_instance": "test",
                "data": data,
                "message": raw,
            }
        )

    yield SimpleNamespace(bot=bot, session=session, send=send, callback=callback, feed=feed, message=message)
    await bot.session.close()
