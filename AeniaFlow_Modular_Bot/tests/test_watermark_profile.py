"""Multiple watermarks, actual image output, saved settings and profile journeys."""

import io
import random
from dataclasses import replace
from unittest.mock import AsyncMock

import pytest
from PIL import Image, ImageChops
from aiogram.types import User
from aeniaflow.core import access, watermark
from aeniaflow.core.database import Database
from aeniaflow.core.runtime import command_seen
from aeniaflow.handlers.commands import wm
from test_private_revision_22 import connect, incoming
from test_revision_21 import photo, requests, texts
from test_revision_24 import buttons, last_panel


@pytest.mark.parametrize("size", [(1200, 800), (640, 1100), (640, 640)])
@pytest.mark.parametrize("count", [3, 5, 8, 12])
@pytest.mark.parametrize("scatter", ["center", "spread"])
def test_every_stamp_fits_with_space_and_random_layout(size, count, scatter):
    options = watermark.Watermark(count=count, scatter=scatter)
    stamp = (90, 28)
    layouts = []
    for seed in range(5):
        positions = watermark.place_watermarks(size, stamp, options, rng=random.Random(seed))
        assert positions and len(positions) == count and len(set(positions)) == count
        layouts.append(positions)
        for index, (x, y) in enumerate(positions):
            assert 0 < x < x + stamp[0] < size[0]
            assert 0 < y < y + stamp[1] < size[1]
            if scatter == "center":
                assert x >= round(size[0] * 0.12) and y >= round(size[1] * 0.12)
                assert x + stamp[0] <= size[0] - round(size[0] * 0.12)
                assert y + stamp[1] <= size[1] - round(size[1] * 0.12)
            for other_x, other_y in positions[index + 1 :]:
                assert (
                    x + stamp[0] + 2 < other_x
                    or other_x + stamp[0] + 2 < x
                    or y + stamp[1] + 2 < other_y
                    or other_y + stamp[1] + 2 < y
                )
        assert min(y for x, y in positions) < size[1] / 2 < max(y + stamp[1] for x, y in positions)
    assert any(layout != layouts[0] for layout in layouts[1:])


@pytest.mark.parametrize("style", ["auto", "glass", "signature"])
@pytest.mark.parametrize("scatter", ["center", "spread"])
@pytest.mark.parametrize("size", [(1000, 650), (500, 900)])
def test_all_twelve_marks_are_actually_rendered_without_outside_changes(
    tmp_path, monkeypatch, style, scatter, size
):
    original = Image.new("RGB", size, "#b2c4d6")
    source = tmp_path / "photo.png"
    original.save(source)
    captured = {}
    place = watermark.place_watermarks

    def record(image_size, stamp_size, options):
        result = place(image_size, stamp_size, options, rng=random.Random(77))
        if result is not None:
            captured.update(positions=result, stamp=stamp_size)
        return result

    monkeypatch.setattr(watermark, "place_watermarks", record)
    image = Image.open(
        io.BytesIO(
            watermark.render_watermark(
                source, watermark.Watermark("Моя подпись", style=style, count=12, scatter=scatter, opacity=40)
            )
        )
    ).convert("RGB")
    difference = ImageChops.difference(image, original)
    assert image.size == size and len(captured["positions"]) == 12
    bw, bh = captured["stamp"]
    for x, y in captured["positions"]:
        box = (x, y, x + bw, y + bh)
        assert difference.crop(box).getbbox() is not None
        difference.paste((0, 0, 0), box)
    assert difference.getbbox() is None


@pytest.mark.parametrize(
    "args", ["--count 0", "--count 13", "--count 2.5", "--count no", "--scatter unknown"]
)
def test_invalid_count_or_scatter_is_explained(args):
    with pytest.raises(ValueError):
        watermark.parse_options(args + " alcLua")


def test_center_scatter_has_smaller_bounds_and_cli_does_not_change_saved_settings(repository):
    repository.upsert_user(User(id=42, is_bot=False, first_name="Owner"))
    repository.set_watermark(42, "count", 8)
    repository.set_watermark(42, "scatter", "spread")
    saved = repository.get_user(42)
    assert watermark.parse_options("alcLua", saved).count == 8
    override = watermark.parse_options("--count=3 --scatter center --opacity 25 Моя подпись", saved)
    assert override.count == 3 and override.scatter == "center" and override.opacity == 25
    assert repository.get_user(42)["watermark_count"] == 8
    center = watermark.place_watermarks(
        (1000, 800), (90, 30), watermark.Watermark(count=12), rng=random.Random(1)
    )
    spread = watermark.place_watermarks(
        (1000, 800), (90, 30), watermark.Watermark(count=12, scatter="spread"), rng=random.Random(1)
    )
    assert min(x for x, _ in spread) < min(x for x, _ in center)
    assert max(x for x, _ in spread) > max(x for x, _ in center)


def test_v5_upgrade_preserves_settings_payment_and_business_reminder(tmp_path):
    path = tmp_path / "upgrade.sqlite3"
    old = Database(str(path))
    old.upsert_user(User(id=42, is_bot=False, first_name="Owner"))
    old.set_watermark(42, "style", "signature")
    old.set_watermark(42, "position", "tr")
    old.set_watermark(42, "opacity", 25)
    old.save_connection("business", 42, True, True)
    old.add_reminder(42, 77, "Original job", 1000, business_connection_id="business")
    order = old.create_order(42, "month", 50, 30)
    old.fulfill_order(old.payload(order["order_id"]), 42, "XTR", 50, "paid")
    expiry = old.premium_until(42)
    for column in ("watermark_count", "watermark_scatter"):
        old.conn.execute(f"ALTER TABLE users DROP COLUMN {column}")
    old.conn.execute("PRAGMA user_version=5")
    old.close()
    migrated = Database(str(path))
    saved = migrated.get_user(42)
    assert (saved["watermark_style"], saved["watermark_position"], saved["watermark_opacity"]) == (
        "signature",
        "tr",
        25,
    )
    assert (saved["watermark_count"], saved["watermark_scatter"]) == (5, "center")
    assert migrated.premium_until(42) == expiry
    assert migrated.reminders(42)[0]["business_connection_id"] == "business"
    migrated.set_watermark(42, "count", 12)
    migrated.set_watermark(42, "scatter", "spread")
    migrated.close()
    reopened = Database(str(path))
    assert reopened.conn.execute("PRAGMA user_version").fetchone()[0] == 8
    assert (
        reopened.get_user(42)["watermark_count"] == 12
        and reopened.get_user(42)["watermark_scatter"] == "spread"
    )
    assert len(list(tmp_path.glob("*.pre-v6-*.bak"))) == 1
    reopened.clear_personal_data(42)
    assert (
        reopened.get_user(42)["watermark_count"] == 5
        and reopened.get_user(42)["watermark_scatter"] == "center"
    )
    assert reopened.premium_until(42) == expiry
    reopened.close()


@pytest.mark.parametrize("business", [False, True])
async def test_select_count_and_style_then_apply_photo_in_same_context(
    client, repository, monkeypatch, tmp_path, business
):
    monkeypatch.setattr(access, "settings", replace(access.settings, admin_ids=frozenset({42})))
    if business:
        await connect(client)
    where = {"chat_id": 77, "business": "business"} if business else {}
    await client.callback("menu:watermark", illustrated=True, **where)
    assert "Количество: 5" in last_panel(client).media.caption
    assert not any(b.callback_data.startswith("wmset:position:") for b in buttons(last_panel(client)))
    for data in ("wmset:count:8", "wmset:scatter:spread", "wmset:style:glass", "wmset:opacity:40"):
        await client.callback(data, illustrated=True, **where)
    assert ".wm --count 8 --scatter spread alcLua" in last_panel(client).media.caption
    await client.callback("use:wm", illustrated=True, **where)
    assert "8 шт." in last_panel(client).media.caption
    send = lambda text: (
        client.feed(business_message=incoming(client, text, sender=42)) if business else client.send(text)
    )
    await send("Моя подпись")
    source = tmp_path / "image.png"
    Image.new("RGB", (1000, 700), "white").save(source)
    monkeypatch.setattr(wm, "download_file", AsyncMock(return_value=str(source)))
    raw = incoming(client, None, sender=42, photo=photo()) if business else client.message(photo=photo())
    await client.feed(**{"business_message" if business else "message": raw})
    result = requests(client, "sendDocument")[-1]
    assert result.chat_id == (77 if business else 42)
    assert result.business_connection_id == ("business" if business else None)
    assert "знаков: 8" in result.caption and "По всему фото" in result.caption
    assert Image.open(io.BytesIO(result.document.data)).size == (1000, 700)
    assert not source.exists()
    await client.callback("wmset:count:1", illustrated=True, **where)
    assert any(b.callback_data == "wmset:position:center" for b in buttons(last_panel(client)))
    assert not any(b.callback_data.startswith("wmset:scatter:") for b in buttons(last_panel(client)))


async def test_invalid_or_peer_watermark_settings_do_not_mutate_owner(client, repository):
    await connect(client)
    for data in ("wmset:count:0", "wmset:count:13", "wmset:scatter:bad"):
        await client.callback(data, illustrated=True, chat_id=77, business="business")
        assert repository.get_user(42)["watermark_count"] == 5
    await client.callback("wmset:count:12", user_id=77, chat_id=77, business="business")
    assert repository.get_user(42)["watermark_count"] == 5


@pytest.mark.parametrize("business", [False, True])
async def test_profile_counts_only_open_own_items_and_buttons_open_directly(client, repository, business):
    if business:
        await connect(client)
    else:
        repository.upsert_user(User(id=42, is_bot=False, first_name="Owner"))
    for user_id in (42, 99):
        for index in range(13):
            repository.save_note(user_id, f"Note {index}", "Body")
            task = repository.add_task(user_id, f"Task {index}")
            if index < 3:
                repository.change_task(user_id, task, True)
    repository.add_reminder(42, 42, "Next", 2000)
    failed = repository.add_reminder(42, 42, "Failed", 2000)
    repository.conn.execute("UPDATE reminders SET status='failed' WHERE id=?", (failed,))
    cancelled = repository.add_reminder(42, 42, "Cancelled", 1000)
    repository.cancel_reminder(42, cancelled)
    repository.add_reminder(99, 99, "Other", 2000)
    where = {"chat_id": 77, "business": "business"} if business else {}
    await client.callback("menu:profile", illustrated=True, **where)
    profile = last_panel(client)
    labels = [b.text for b in buttons(profile)]
    assert "Заметки · 13" in labels and "Задачи · 10" in labels
    assert "Напоминания · 1 !" in labels and "Автоответ · выкл" in labels
    assert "Не доставлено напоминаний: 1" in profile.media.caption
    assert ".profile" in profile.media.caption and "ID" not in profile.media.caption
    assert (
        "ЛС подключены" in profile.media.caption
        if business
        else "Статус ЛС ещё не получен" in profile.media.caption
    )
    assert len(profile.reply_markup.inline_keyboard) == 7
    assert all(len(row) == 2 for row in profile.reply_markup.inline_keyboard[:-1])
    assert not any(b.callback_data == "menu:payments" for b in buttons(profile))
    for code, heading in (("notes", "Заметки"), ("tasks", "Задачи"), ("reminders", "Напоминания")):
        await client.callback(f"menu:{code}", illustrated=True, **where)
        assert heading in last_panel(client).media.caption
        assert (
            any(b.callback_data == "menu:profile" for b in buttons(last_panel(client)))
            and buttons(last_panel(client))[-1].callback_data == "menu:profile"
        )
    await client.callback("menu:premium", illustrated=True, **where)
    assert any(b.callback_data == "menu:payments" for b in buttons(last_panel(client)))
    await client.callback("menu:help", illustrated=True, **where)
    assert any(b.callback_data == "menu:paysupport" for b in buttons(last_panel(client)))


async def test_admin_profile_still_has_payment_history_and_free_plus(client, monkeypatch):
    monkeypatch.setattr(access, "settings", replace(access.settings, admin_ids=frozenset({42, 99})))
    await client.send(".profile", user_id=99)
    assert "Администратор · Plus без срока" in texts(client)[-1]
    await client.callback("menu:premium", user_id=99, illustrated=True)
    assert any(b.callback_data == "menu:payments" for b in buttons(last_panel(client)))
    assert not requests(client, "sendInvoice")
    command_seen.clear()
