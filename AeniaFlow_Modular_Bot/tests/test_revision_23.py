import asyncio
import io
import time
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock
import pytest
from PIL import Image, ImageChops
from aiogram.types import Chat, User
from aeniaflow.core import access
from aeniaflow.core.database import Database
from aeniaflow.core.watermark import Watermark, parse_options, render_watermark
from aeniaflow.catalog import PLANS
from aeniaflow.handlers.commands import wm
from aeniaflow.handlers.system import mutes
from config import Settings
from test_private_revision_22 import connect, incoming
from test_revision_21 import requests, texts, photo


@pytest.mark.parametrize("where", ["peer", "owner", "menu"])
async def test_unmute_button_in_both_chats_updates_both_notices(client, repository, where):
    await connect(client)
    await client.feed(business_message=incoming(client, ".mute", sender=42))
    row = repository.dialogs(42)[0]
    notices = requests(client, "sendMessage")
    assert {r.chat_id for r in notices} == {42, 77}
    for notice in notices:
        button = notice.reply_markup.inline_keyboard[0][0]
        assert button.text == "Размутить" and button.style == "success"
    await client.callback(
        f"mute:off:{row['id']}",
        chat_id=77 if where == "peer" else 42,
        business="business" if where == "peer" else None,
        mid=row["mute_message_id"] if where == "peer" else row["owner_message_id"] if where == "owner" else 1,
        illustrated=where == "menu",
    )
    assert repository.dialog(42, row["id"])["muted"] == 0
    edits = requests(client, "editMessageText")
    assert {(r.chat_id, r.message_id) for r in edits} == {
        (77, row["mute_message_id"]),
        (42, row["owner_message_id"]),
    }
    assert all("мут снят" in r.text and r.reply_markup is None for r in edits)
    assert next(r for r in edits if r.chat_id == 77).business_connection_id == "business"


async def test_peer_cannot_press_unmute_and_owner_cannot_use_it_in_another_dialog(client, repository):
    await connect(client)
    await client.feed(business_message=incoming(client, ".mute", sender=42))
    row = repository.dialogs(42)[0]
    await client.callback(f"mute:off:{row['id']}", user_id=77, chat_id=77, business="business")
    await client.callback(f"mute:off:{row['id']}", chat_id=88, business="business")
    await client.callback(f"mute:off:{row['id']}", user_id=99)
    assert repository.dialog(42, row["id"])["muted"] == 1
    assert not requests(client, "editMessageText")


async def test_unmute_still_available_after_business_disconnect(client, repository):
    await connect(client)
    await client.feed(business_message=incoming(client, ".mute", sender=42))
    row = repository.dialogs(42)[0]
    await connect(client, enabled=False, reply=False, delete=False)
    await client.callback(
        f"mute:off:{row['id']}", chat_id=77, business="business", mid=row["mute_message_id"]
    )
    assert repository.dialog(42, row["id"])["muted"] == 0


@pytest.mark.parametrize("argument", ["10m", "10", "1d", "123456789"])
async def test_mute_has_no_duration_arguments(client, repository, argument):
    await connect(client)
    await client.feed(business_message=incoming(client, ".mute " + argument, sender=42))
    assert not repository.dialogs(42)[0]["muted"]
    assert "без срока" in texts(client)[-1]


def test_v3_migration_promotes_active_mutes_and_preserves_inactive(tmp_path):
    path = tmp_path / "state.sqlite3"
    repo = Database(str(path))
    repo.upsert_user(User(id=42, is_bot=False, first_name="Owner"))
    first = repo.remember_dialog(42, "business", Chat(id=77, type="private", first_name="Active"))
    second = repo.remember_dialog(42, "business", Chat(id=88, type="private", first_name="Expired"))
    repo.conn.execute(
        "UPDATE private_dialogs SET muted_until=? WHERE id=?", (int(time.time()) + 60, first["id"])
    )
    repo.conn.execute("UPDATE private_dialogs SET muted_until=1 WHERE id=?", (second["id"],))
    for column in ("muted", "mute_message_id", "owner_message_id"):
        repo.conn.execute(f"ALTER TABLE private_dialogs DROP COLUMN {column}")
    for column in ("watermark_style", "watermark_position", "watermark_opacity"):
        repo.conn.execute(f"ALTER TABLE users DROP COLUMN {column}")
    repo.conn.execute("PRAGMA user_version=3")
    repo.close()
    current = Database(str(path))
    assert current.dialog(42, first["id"])["muted"] == 1
    assert current.dialog(42, second["id"])["muted"] == 0
    current.close()
    reopened = Database(str(path))
    assert reopened.dialog(42, first["id"])["muted"] == 1
    assert len(list(tmp_path.glob("*.pre-v4-*.bak"))) == 1
    reopened.close()


async def test_mute_never_expires_and_is_not_pruned(repository, client, monkeypatch):
    await connect(client)
    await client.feed(business_message=incoming(client, ".mute", sender=42))
    row = repository.dialogs(42)[0]
    future = int(time.time()) + 400 * 86400
    monkeypatch.setattr(time, "time", lambda: future)
    for identifier in range(1000, 1205):
        repository.remember_dialog(42, "business", Chat(id=identifier, type="private", first_name="Peer"))
    assert repository.dialog(42, row["id"])["muted"] == 1
    await client.feed(business_message=incoming(client))
    assert requests(client, "deleteBusinessMessages")


async def test_concurrent_mute_and_unmute_cannot_leave_stale_notice(client, repository, monkeypatch):
    await connect(client)
    row = repository.remember_dialog(42, "business", Chat(id=77, type="private", first_name="Peer"))
    started, finish = asyncio.Event(), asyncio.Event()
    actual = mutes.update_notice

    async def delayed(bot, row, **kwargs):
        if row["muted"] and not kwargs.get("personal"):
            started.set()
            await finish.wait()
        return await actual(bot, row, **kwargs)

    monkeypatch.setattr(mutes, "update_notice", delayed)
    first = asyncio.create_task(mutes.enable_mute(client.bot, row))
    await started.wait()
    second = asyncio.create_task(mutes.disable_mute(client.bot, row))
    finish.set()
    await asyncio.gather(first, second)
    assert repository.dialog(42, row["id"])["muted"] == 0
    assert all("мут снят" in r.text for r in requests(client, "editMessageText"))


@pytest.mark.parametrize("plan", list(PLANS))
async def test_every_plus_term_is_stars_bound_and_extends_exact_days(client, repository, plan):
    product = PLANS[plan]
    await client.callback("plan:" + plan)
    assert product["label"] in texts(client)[-1]
    assert str(product["stars"]) in texts(client)[-1]
    assert not requests(client, "sendInvoice")
    await client.callback("pay:" + plan)
    invoice = requests(client, "sendInvoice")[-1]
    assert invoice.currency == "XTR" and invoice.provider_token == ""
    assert invoice.prices[0].amount == product["stars"]
    order = repository.order(invoice.payload[4:])
    result = repository.fulfill_order(
        invoice.payload, 42, "XTR", product["stars"], "charge-" + plan, now=order["created_at"]
    )
    assert result.expires_at - order["created_at"] == product["days"] * 86400


@pytest.mark.parametrize("style", ["auto", "glass", "signature"])
@pytest.mark.parametrize("background", ["white", "#102236"])
def test_watermark_is_visible_subtle_and_stays_in_corner(tmp_path, style, background):
    original = Image.new("RGB", (1000, 600), background)
    source = tmp_path / "source.png"
    original.save(source)
    result = Image.open(
        io.BytesIO(render_watermark(source, Watermark("alcLua", style, "br", 40, count=1)))
    ).convert("RGB")
    box = ImageChops.difference(result, original).getbbox()
    assert box and box[0] > 700 and box[1] > 500 and box[2] < 1000 and box[3] < 600
    assert result.getpixel((10, 10)) == original.getpixel((10, 10))
    assert result.size == original.size


@pytest.mark.parametrize("position", ["tl", "tr", "bl", "br", "center"])
def test_watermark_positions_and_cyrillic(tmp_path, position):
    original = Image.new("RGB", (800, 600), "#b2c4d6")
    source = tmp_path / "photo.png"
    original.save(source)
    result = Image.open(
        io.BytesIO(render_watermark(source, Watermark("Моя подпись", position=position, count=1)))
    ).convert("RGB")
    box = ImageChops.difference(original, result).getbbox()
    assert box and box[0] >= 0 and box[2] <= 800
    if position == "center":
        assert box[0] < 400 < box[2] and box[1] < 300 < box[3]
    else:
        assert (box[0] < 400) == position.endswith("l")
        assert (box[1] < 300) == position.startswith("t")


async def test_watermark_settings_apply_to_file_and_survive_restart(
    client, repository, tmp_path, monkeypatch
):
    monkeypatch.setattr(access, "settings", replace(access.settings, admin_ids=frozenset({42})))
    await client.callback("menu:watermark")
    for data in ("wmset:count:1", "wmset:style:glass", "wmset:position:tl", "wmset:opacity:40"):
        await client.callback(data)
    row = repository.get_user(42)
    assert (
        row["watermark_style"] == "glass"
        and row["watermark_position"] == "tl"
        and row["watermark_opacity"] == 40
    )
    source = tmp_path / "photo.png"
    Image.new("RGB", (800, 600), "white").save(source)
    monkeypatch.setattr(wm, "download_file", AsyncMock(return_value=str(source)))
    await client.feed(message=client.message(photo=photo(), caption=".wm alcLua"))
    sent = requests(client, "sendDocument")[-1]
    image = Image.open(io.BytesIO(sent.document.data)).convert("RGB")
    assert ImageChops.difference(image, Image.new("RGB", image.size, "white")).getbbox()[0] < 100
    assert not source.exists()
    dbpath = repository.conn.execute("PRAGMA database_list").fetchone()["file"]
    other = Database(dbpath)
    assert other.get_user(42)["watermark_style"] == "glass"
    other.close()


def test_watermark_flags_and_reject_invalid_options():
    value = parse_options("--style glass --pos center --opacity 40 alcLua")
    assert value == Watermark("alcLua", "glass", "center", 40)
    for args in ("--opacity 100 title", "--style bad title", "--pos bad text", "--oops test"):
        with pytest.raises(ValueError):
            parse_options(args)


def test_contacts_restored_without_secrets_and_docs_are_complete(monkeypatch):
    monkeypatch.setenv("SUPPORT_USERNAME", "")
    monkeypatch.delenv("BOT_TOKEN", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    settings = Settings()
    assert settings.support_username == "alcLua" and settings.news_channel_url == "https://t.me/AeniaFlow"
    assert not settings.bot_token and not settings.openai_api_key
    for path in Path("legal").glob("*.md"):
        text = path.read_text()
        assert "alcLua" in text and "https://t.me/alcLua" in text
        assert "[указать" not in text and "[действующий" not in text and "реквизит" not in text.lower()
