from dataclasses import replace
from unittest.mock import AsyncMock
from io import BytesIO
import pytest
from PIL import Image
from aiogram.types import Message, User
from aeniaflow.core import access
from aeniaflow.core.inputs import recent_media, media_source, TTL
from aeniaflow.catalog import FEATURES, CATEGORIES
from aeniaflow.handlers.system import command_dispatcher
from aeniaflow.handlers.commands import media_tools, wm


def requests(client, method):
    return [r for r in client.session.requests if r.__api_method__ == method]


def texts(client):
    return [
        getattr(r, "text", None)
        or getattr(getattr(r, "media", None), "caption", None)
        or getattr(r, "caption", None)
        or ""
        for r in client.session.requests
        if r.__api_method__
        in {"sendMessage", "editMessageMedia", "sendPhoto", "editMessageMedia", "editMessageCaption"}
    ]


@pytest.fixture
def owners(monkeypatch):
    configured = replace(access.settings, admin_ids=frozenset({42, 99}))
    monkeypatch.setattr(access, "settings", configured)
    return configured


def photo():
    return [{"file_id": "photo-1", "file_unique_id": "unique", "width": 80, "height": 40}]


async def test_start_is_native_and_navigation_edits_same_panel(client):
    await client.send("/start")
    await client.callback("menu:catalog", mid=100)
    await client.callback("cat:media:0", mid=100)
    await client.callback("feat:wm", mid=100)
    await client.callback("menu:home", mid=100)
    assert len(requests(client, "sendPhoto")) == 1
    assert not requests(client, "sendMessage")
    assert len(requests(client, "editMessageMedia")) == 4
    assert all(r.message_id == 100 for r in requests(client, "editMessageMedia"))
    assert "успешно подключён" not in " ".join(texts(client))


async def test_legacy_picture_menu_is_updated_in_place(client):
    raw = client.message(photo=photo())
    raw["from"] = {"id": 123456, "is_bot": True, "first_name": "Bot"}
    await client.feed(
        callback_query={
            "id": "old",
            "from": {"id": 42, "is_bot": False, "first_name": "Human"},
            "chat_instance": "test",
            "data": "menu:home",
            "message": raw,
        }
    )
    assert requests(client, "editMessageMedia")
    assert not requests(client, "deleteMessage")
    assert not requests(client, "sendPhoto")


async def test_all_categories_and_feature_cards_open_with_native_buttons(client):
    codes = [code for _, group in CATEGORIES.values() for code in group]
    assert len(codes) == len(set(codes)) == len(FEATURES)
    assert set(codes) == set(FEATURES)
    for category in CATEGORIES:
        await client.callback(f"cat:{category}:0")
    for code, (_, usage) in FEATURES.items():
        assert usage.startswith(".") and "ответом" not in usage
        await client.callback(f"feat:{code}")
    assert len(requests(client, "editMessageMedia")) == len(CATEGORIES) + len(FEATURES)
    for request in requests(client, "editMessageMedia"):
        for row in request.reply_markup.inline_keyboard:
            for button in row:
                assert 0 < len(button.callback_data.encode()) <= 64


async def test_dot_commands_work_slash_tools_are_rejected(client):
    await client.send(".calc (12+5)*3")
    assert "51" in texts(client)[-1]
    await client.send("/calc 2+2")
    assert "Префикс команд — точка" in texts(client)[-1]
    await client.send(".quote <Привет>")
    assert "&lt;Привет&gt;" in texts(client)[-1]
    await client.send("/paysupport")
    assert "Поддержка платежей" in texts(client)[-1]


@pytest.mark.parametrize("owner", [42, 99])
async def test_both_admins_have_plus_without_purchase(client, repository, owners, owner):
    await client.send(".leet Hello", user_id=owner)
    assert "входит в AeniaFlow+" not in texts(client)[-1]
    assert texts(client)[-1]
    assert not repository.is_premium(owner)
    await client.callback("menu:profile", user_id=owner)
    assert "Администратор · Plus без срока" in texts(client)[-1]
    await client.callback("pay:month", user_id=owner)
    assert not requests(client, "sendInvoice")


async def test_regular_user_still_requires_stars(client, owners):
    await client.send(".leet Hello", user_id=77)
    assert "входит в AeniaFlow+" in texts(client)[-1]


async def test_admin_is_not_blocked_by_channel_requirement(client, owners, monkeypatch):
    monkeypatch.setattr(command_dispatcher, "settings", replace(owners, news_channel="@required"))
    await client.send(".leet Hello")
    assert not requests(client, "getChatMember")
    assert "Подпишитесь" not in texts(client)[-1]


@pytest.mark.parametrize("order", ["caption", "file_first", "command_first"])
@pytest.mark.parametrize(
    "command,width,height", [(".resize 160", 160, 80), (".rotate 90", 40, 80), (".mirror", 80, 40)]
)
async def test_photo_transforms_without_reply_through_real_dispatcher(
    client, tmp_path, monkeypatch, order, command, width, height
):
    download = AsyncMock()
    monkeypatch.setattr(media_tools, "download_file", download)
    if order == "caption":
        await client.feed(message=client.message(photo=photo(), caption=command))
    else:
        if order == "file_first":
            await client.feed(message=client.message(photo=photo()))
        await client.send(command)
        if order == "command_first":
            await client.feed(message=client.message(photo=photo()))
    download.assert_not_awaited()
    assert not requests(client, "sendDocument")
    assert "Команда не найдена" in " ".join(texts(client))


async def test_image_document_is_accepted_without_reply(client, tmp_path, monkeypatch):
    monkeypatch.setattr(access, "settings", replace(access.settings, admin_ids=frozenset({42})))
    source = tmp_path / "photo.png"
    Image.new("RGB", (320, 160)).save(source)
    monkeypatch.setattr(wm, "download_file", AsyncMock(return_value=str(source)))
    await client.feed(
        message=client.message(
            document={"file_id": "doc", "file_unique_id": "doc", "mime_type": "image/png"},
            caption=".wm --count 1 Тест",
        )
    )
    assert requests(client, "sendDocument")


async def test_pending_file_is_scoped_to_user_and_cancelled(client, tmp_path, monkeypatch):
    monkeypatch.setattr(access, "settings", replace(access.settings, admin_ids=frozenset({42})))
    download = AsyncMock()
    monkeypatch.setattr(wm, "download_file", download)
    await client.send(".wm --count 1 Тест")
    await client.feed(message=client.message(user_id=99, photo=photo()))
    download.assert_not_awaited()
    await client.send(".cancel")
    await client.feed(message=client.message(photo=photo()))
    download.assert_not_awaited()


async def test_wrong_attachment_does_not_reuse_old_photo(client, monkeypatch):
    monkeypatch.setattr(access, "settings", replace(access.settings, admin_ids=frozenset({42})))
    download = AsyncMock()
    monkeypatch.setattr(wm, "download_file", download)
    await client.feed(message=client.message(photo=photo()))
    await client.feed(
        message=client.message(
            document={"file_id": "pdf", "file_unique_id": "pdf", "mime_type": "application/pdf"},
            caption=".wm --count 1 Тест",
        )
    )
    download.assert_not_awaited()
    assert "Отправьте фото" in texts(client)[-1]


async def test_next_file_is_not_blocked_by_command_cooldown(client, monkeypatch, tmp_path):
    monkeypatch.setattr(access, "settings", replace(access.settings, admin_ids=frozenset({42})))
    monkeypatch.setattr(command_dispatcher, "settings", replace(access.settings, command_cooldown=60))
    source = tmp_path / "photo.jpg"
    Image.new("RGB", (320, 160)).save(source)
    monkeypatch.setattr(wm, "download_file", AsyncMock(return_value=str(source)))
    await client.send(".wm --count 1 Тест")
    await client.feed(message=client.message(photo=photo()))
    assert requests(client, "sendDocument")


async def test_organizer_buttons_create_open_and_delete_own_note(client, repository):
    await client.callback("input:note")
    await client.send("Идея | <b>Текст</b>")
    row = repository.notes(42)[0]
    assert row["body"] == "<b>Текст</b>"
    await client.callback("menu:notes")
    await client.callback(f'note:open:42:{row["id"]}:0')
    assert "&lt;b&gt;Текст&lt;/b&gt;" in texts(client)[-1]
    await client.callback(f'note:delete:42:{row["id"]}:0', user_id=99)
    assert repository.note(42, row["id"])
    await client.callback(f'note:ask:42:{row["id"]}:0')
    assert repository.note(42, row["id"])
    await client.callback(f'note:delete:42:{row["id"]}:0')
    assert not repository.note(42, row["id"])


async def test_task_buttons_refresh_status_and_reminder_cancel(client, repository):
    await client.callback("input:todo")
    await client.send("Проверить бота")
    task = repository.tasks(42)[0]
    await client.callback(f'task:done:42:{task["id"]}')
    assert repository.tasks(42)[0]["done"]
    assert any(
        "✓ Проверить" in b.text
        for row in requests(client, "editMessageMedia")[-1].reply_markup.inline_keyboard
        for b in row
    )
    await client.callback(f'task:undo:42:{task["id"]}')
    assert not repository.tasks(42)[0]["done"]
    await client.callback("input:remind")
    await client.send("1h Перерыв")
    reminder = repository.reminders(42)[0]
    await client.callback(f'remind:cancel:42:{reminder["id"]}')
    assert not repository.reminders(42)


async def test_search_button_accepts_plain_text_and_opens_results(client):
    await client.callback("input:find")
    await client.send("фото")
    result = requests(client, "sendMessage")[-1]
    assert "Результаты поиска" in result.text
    assert any(
        b.callback_data.startswith("run:blur:") for row in result.reply_markup.inline_keyboard for b in row
    )


async def test_new_menu_cancels_previous_form(client, repository):
    await client.callback("input:todo")
    await client.callback("menu:home")
    await client.send("Это не задача")
    assert not repository.tasks(42)


async def test_private_views_and_inputs_do_not_leak_into_group(client, repository):
    repository.save_note(42, "SECRET", "BODY")
    for data in ("menu:notes", "menu:tasks", "menu:reminders", "input:note"):
        await client.callback(data, chat_id=-1001)
    assert all("SECRET" not in text and "личном" in text for text in texts(client))


async def test_business_owner_commands_reach_connected_chat(client, repository):
    repository.remember_peer(User(id=77, is_bot=False, first_name="Peer"))
    repository.save_connection("business", 42, True, True)
    repository.save_autoreply(42, enabled=True)
    await client.feed(
        business_message=client.message(
            user_id=42, chat_id=77, business_connection_id="business", text=".calc 8*7"
        )
    )
    replies = requests(client, "sendMessage")
    assert len(replies) == 1 and "56" in replies[0].text
    assert replies[0].chat_id == 77 and replies[0].business_connection_id == "business"


async def test_business_customer_cannot_run_owner_commands(client, repository):
    repository.save_connection("business", 42, True, True)
    await client.feed(
        business_message=client.message(
            user_id=77, chat_id=77, business_connection_id="business", text=".calc 8*7"
        )
    )
    assert not requests(client, "sendMessage")


async def test_business_owner_can_open_personal_tools_but_export_asks_before_sharing(client, repository):
    repository.remember_peer(User(id=77, is_bot=False, first_name="Peer"))
    repository.save_connection("business", 42, True, True)
    repository.save_note(42, "SECRET", "BODY")
    for command in (".notes", ".export", ".profile"):
        await client.feed(
            business_message=client.message(
                user_id=42, chat_id=77, business_connection_id="business", text=command
            )
        )
    assert not requests(client, "sendDocument")
    assert any("SECRET" in text for text in texts(client))
    assert any("Файл в этом диалоге увидит собеседник" in text for text in texts(client))
    assert not any("Личные разделы и настройки открываются" in text for text in texts(client))


@pytest.mark.parametrize("enabled,can_reply", [(False, True), (True, False)])
async def test_business_disabled_connection_cannot_execute(client, repository, enabled, can_reply):
    repository.save_connection("business", 42, enabled, can_reply)
    await client.feed(
        business_message=client.message(
            user_id=42, chat_id=77, business_connection_id="business", text=".calc 8*7"
        )
    )
    # The command stays blocked, but the verified owner now gets an explanation
    # in their bot DM instead of silent failure in the connected conversation.
    notices = requests(client, "sendMessage")
    assert len(notices) == 1
    assert notices[0].chat_id == 42 and notices[0].business_connection_id is None
    assert "не выполнена" in notices[0].text
    assert not requests(client, "sendPhoto")


async def test_business_last_incoming_photo_is_scoped_to_connection(
    client, repository, tmp_path, monkeypatch
):
    monkeypatch.setattr(access, "settings", replace(access.settings, admin_ids=frozenset({42})))
    repository.save_connection("business", 42, True, True)
    source = tmp_path / "photo.jpg"
    Image.new("RGB", (320, 160)).save(source)
    monkeypatch.setattr(wm, "download_file", AsyncMock(return_value=str(source)))
    await client.feed(
        business_message=client.message(
            user_id=77, chat_id=77, business_connection_id="business", photo=photo()
        )
    )
    await client.feed(
        business_message=client.message(
            user_id=42, chat_id=77, business_connection_id="business", text=".wm --count 1 Тест"
        )
    )
    result = requests(client, "sendDocument")[0]
    assert result.business_connection_id == "business" and result.chat_id == 77
    await client.send(".wm --count 1 Тест")
    assert "Отправьте фото" in texts(client)[-1]
    assert len(requests(client, "sendDocument")) == 1


def test_recent_media_expires_and_does_not_cross_topics(client):
    first = Message.model_validate(client.message(photo=photo(), message_thread_id=1))
    from aeniaflow.core.inputs import remember_media

    remember_media(first)
    key = next(iter(recent_media))
    stamp, value = recent_media[key]
    other = first.model_copy(update={"photo": None, "message_thread_id": 2})
    assert media_source(other, "photo") is None
    recent_media[key] = (stamp - TTL - 1, value)
    assert media_source(first.model_copy(update={"photo": None}), "photo") is None


@pytest.mark.parametrize("owner", [42, 99])
async def test_both_admins_have_plus_in_business_commands(client, repository, owners, owner):
    repository.remember_peer(User(id=77, is_bot=False, first_name="Peer"))
    repository.save_connection(f"business-{owner}", owner, True, True)
    await client.feed(
        business_message=client.message(
            user_id=owner, chat_id=77, business_connection_id=f"business-{owner}", text=".leet Hello"
        )
    )
    result = requests(client, "sendMessage")[-1]
    assert "входит в AeniaFlow+" not in result.text
    assert result.business_connection_id == f"business-{owner}"


async def test_media_button_accepts_parameters_then_file(client, tmp_path, monkeypatch):
    monkeypatch.setattr(access, "settings", replace(access.settings, admin_ids=frozenset({42})))
    source = tmp_path / "photo.jpg"
    Image.new("RGB", (320, 160)).save(source)
    monkeypatch.setattr(wm, "download_file", AsyncMock(return_value=str(source)))
    await client.callback("use:wm")
    await client.send("Тест")
    assert "Отправьте фото" in texts(client)[-1]
    await client.feed(message=client.message(photo=photo()))
    result = requests(client, "sendDocument")[-1]
    assert Image.open(BytesIO(result.document.data)).size == (320, 160)


async def test_disabled_business_cannot_be_turned_on_by_old_button(client, repository):
    repository.save_connection("business", 42, False, True)
    await client.callback("auto:on")
    assert not repository.get_autoreply(42)["enabled"]
