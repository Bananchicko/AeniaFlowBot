"""User journeys for the flat menu and command-to-confirmation behavior."""

from dataclasses import replace
from io import BytesIO
from unittest.mock import AsyncMock
import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Chat, User
from PIL import Image
from aeniaflow.core import access
from aeniaflow.core.runtime import command_seen
from aeniaflow.core.inputs import pending_input
from aeniaflow.handlers.commands import COMMANDS, wm
from test_private_revision_22 import connect, incoming
from test_revision_21 import requests, texts, photo


def buttons(request):
    return [b for row in request.reply_markup.inline_keyboard for b in row]


def last_panel(client):
    return requests(client, "editMessageMedia")[-1]


async def test_home_to_calculator_has_no_category_or_detail_step(client):
    await client.send("/start")
    home = requests(client, "sendPhoto")[-1]
    assert [b.text for b in buttons(home)][:3] == ["Базовые функции", "Plus функции", "Профиль"]
    assert len(buttons(home)) == 3
    await client.callback(buttons(home)[0].callback_data, mid=100, illustrated=True)
    functions = last_panel(client)
    assert not any(b.callback_data.startswith(("cat:", "feat:")) for b in buttons(functions))
    calc = next(b for b in buttons(functions) if b.text == "Калькулятор")
    await client.callback(calc.callback_data, mid=100, illustrated=True)
    prompt = last_panel(client)
    assert "Калькулятор" in prompt.media.caption and "Введите выражение" in prompt.media.caption
    assert not any(b.text == "Использовать" for b in buttons(prompt))
    await client.send("6*7")
    assert "42" in texts(client)[-1]
    assert all(r.message_id != 100 for r in requests(client, "deleteMessage"))


@pytest.mark.parametrize("mode,pages", [("free", 3), ("plus", 2)])
async def test_tool_pages_are_even_rows_and_never_expose_account_management(client, mode, pages):
    all_tools = set()
    for page in range(pages):
        await client.callback(f"list:{mode}:{page}", mid=100, illustrated=True)
        panel = last_panel(client)
        tool_rows = [
            row for row in panel.reply_markup.inline_keyboard if row[0].callback_data.startswith("run:")
        ]
        assert tool_rows and all(len(row) == 2 for row in tool_rows)
        for row in tool_rows:
            for button in row:
                assert len(button.callback_data.encode()) <= 64
                code = button.callback_data.split(":")[1]
                assert code not in all_tools
                all_tools.add(code)
        assert f"{page+1} / {pages}" in [b.text for b in buttons(panel)]
        assert not any(b.callback_data.startswith(("cat:", "feat:")) for b in buttons(panel))
    assert not all_tools & {"chats", "mutelist", "payments", "settings", "profile", "organizer"}
    assert (
        {"msay", "calc", "note", "afk"} <= all_tools
        if mode == "free"
        else {"gpt", "wm", "panic"} <= all_tools
    )


async def test_back_returns_to_same_page_and_cancels_pending_input(client, monkeypatch):
    execute = AsyncMock()
    monkeypatch.setitem(COMMANDS, "msay", execute)
    await client.callback("run:msay:free:0", mid=100, illustrated=True)
    back = next(b for b in buttons(last_panel(client)) if b.text == "‹ Назад")
    assert back.callback_data == "list:free:0"
    await client.callback(back.callback_data, mid=100, illustrated=True)
    await client.send("Не нужно превращать это в картинку")
    execute.assert_not_awaited()
    assert "1 / 3" in [b.text for b in buttons(last_panel(client))]


async def test_plus_opens_tools_and_only_gates_when_a_function_is_started(client):
    await client.callback("list:plus:0", illustrated=True)
    assert any(b.text == "Спросить ИИ" for b in buttons(last_panel(client)))
    assert not requests(client, "sendInvoice")
    await client.callback("run:gpt:plus:0", illustrated=True)
    assert "Stars" in last_panel(client).media.caption
    assert any(b.callback_data == "plan:day" for b in buttons(last_panel(client)))
    assert not requests(client, "sendInvoice")


async def test_admin_starts_plus_function_directly(client, monkeypatch):
    monkeypatch.setattr(access, "settings", replace(access.settings, admin_ids=frozenset({42, 99})))
    await client.callback("run:gpt:plus:0", user_id=99, illustrated=True)
    assert "Напишите свой вопрос" in last_panel(client).media.caption
    assert not requests(client, "sendInvoice")


async def test_profile_counts_all_own_dialogs_not_only_first_page(client, repository):
    repository.upsert_user(User(id=42, is_bot=False, first_name="Alice"))
    for index in range(12):
        row = repository.remember_dialog(
            42, "biz", Chat(id=1000 + index, type="private", first_name=f"Чат {index}")
        )
        repository.set_private_mute(42, row["id"], index < 10)
    other = repository.remember_dialog(99, "other", Chat(id=5000, type="private", first_name="Чужой"))
    repository.set_private_mute(99, other["id"], True)
    await client.callback("menu:profile", illustrated=True)
    panel = last_panel(client)
    assert "Чаты · 12" in [b.text for b in buttons(panel)]
    assert "Муты · 10" in [b.text for b in buttons(panel)]
    assert all(len(row) == 2 for row in panel.reply_markup.inline_keyboard[:-1])
    assert buttons(panel)[-1].callback_data == "menu:home"
    await client.callback("menu:mutelist", illustrated=True)
    assert (
        any(b.callback_data == "menu:profile" for b in buttons(last_panel(client)))
        and buttons(last_panel(client))[-1].callback_data == "menu:profile"
    )
    assert "Чужой" not in texts(client)[-1]


async def test_mute_replaces_only_own_command_before_showing_confirmation(client, repository):
    await connect(client)
    command = incoming(client, ".mute", sender=42)
    await client.feed(business_message=command)
    deletion = requests(client, "deleteBusinessMessages")[0]
    assert deletion.message_ids == [command["message_id"]]
    assert deletion.business_connection_id == "business"
    notices = requests(client, "sendMessage")
    assert {r.chat_id for r in notices} == {42, 77}
    assert client.session.requests.index(deletion) < client.session.requests.index(notices[0])
    assert all("✓ Готово · мут включён" in r.text for r in notices)
    assert all(buttons(r)[0].text == "Размутить" for r in notices)
    row = repository.dialogs(42)[0]
    assert row["muted"] == 1
    assert command["message_id"] not in repository.recent_private_messages(42, row["id"], 100)
    peer = incoming(client, "Это новое входящее")
    await client.feed(business_message=peer)
    assert requests(client, "deleteBusinessMessages")[-1].message_ids == [peer["message_id"]]


async def test_repeated_mute_shows_fresh_receipt_and_retires_old_one(client, repository):
    await connect(client)
    await client.feed(business_message=incoming(client, ".mute", sender=42))
    before = repository.dialogs(42)[0]
    command_seen.clear()
    command = incoming(client, ".mute", sender=42)
    await client.feed(business_message=command)
    after = repository.dialogs(42)[0]
    assert after["mute_message_id"] != before["mute_message_id"]
    assert after["owner_message_id"] == before["owner_message_id"]
    deleted_ids = [mid for r in requests(client, "deleteBusinessMessages") for mid in r.message_ids]
    assert command["message_id"] in deleted_ids and before["mute_message_id"] in deleted_ids
    await client.callback(
        f"mute:off:{after['id']}", chat_id=77, mid=after["mute_message_id"], business="business"
    )
    assert not repository.dialog(42, after["id"])["muted"]
    assert requests(client, "editMessageText")[-1].reply_markup is None


@pytest.mark.parametrize("was_muted", [True, False])
async def test_unmute_command_is_replaced_by_current_confirmation(client, repository, was_muted):
    await connect(client)
    if was_muted:
        await client.feed(business_message=incoming(client, ".mute", sender=42))
        command_seen.clear()
    command = incoming(client, ".unmute", sender=42)
    await client.feed(business_message=command)
    assert [command["message_id"]] in [r.message_ids for r in requests(client, "deleteBusinessMessages")]
    last = [r for r in requests(client, "sendMessage") if r.chat_id == 77][-1]
    assert "Готово · мут снят" in last.text and last.reply_markup is None
    assert not repository.dialogs(42)[0]["muted"]


async def test_failed_command_cleanup_keeps_mute_and_explains_in_owner_receipt(
    client, repository, monkeypatch
):
    await connect(client)
    original = client.session.make_request

    async def reject_deletion(bot, method, timeout=None):
        if method.__api_method__ == "deleteBusinessMessages":
            raise TelegramBadRequest(method=method, message="MESSAGE_DELETE_FORBIDDEN")
        return await original(bot, method, timeout)

    monkeypatch.setattr(client.session, "make_request", reject_deletion)
    await client.feed(business_message=incoming(client, ".mute", sender=42))
    assert repository.dialogs(42)[0]["muted"]
    owner_notice = next(r for r in requests(client, "sendMessage") if r.chat_id == 42)
    assert "не разрешил удалить сообщение с командой" in owner_notice.text
    assert buttons(owner_notice)[0].text == "Размутить"


async def test_blocked_peer_confirmation_still_leaves_owner_an_unmute_button(client, repository, monkeypatch):
    await connect(client)
    original = client.session.make_request

    async def reject_peer_send(bot, method, timeout=None):
        if method.__api_method__ == "sendMessage" and method.chat_id == 77:
            raise TelegramBadRequest(method=method, message="BUSINESS_PEER_INVALID")
        return await original(bot, method, timeout)

    monkeypatch.setattr(client.session, "make_request", reject_peer_send)
    await client.feed(business_message=incoming(client, ".mute", sender=42))
    owner_notice = requests(client, "sendMessage")[-1]
    assert owner_notice.chat_id == 42 and "показать подтверждение" in owner_notice.text
    row = repository.dialogs(42)[0]
    await client.callback(buttons(owner_notice)[0].callback_data, mid=row["owner_message_id"])
    assert not repository.dialog(42, row["id"])["muted"]


@pytest.mark.parametrize("command", [".unknown", ".mute 10m", ".calc@DifferentBot 2+2", ".unmute tomorrow"])
async def test_rejected_or_unaddressed_commands_are_not_deleted(client, command):
    await connect(client)
    await client.feed(business_message=incoming(client, command, sender=42))
    assert not requests(client, "deleteBusinessMessages")


async def test_button_execution_never_deletes_menu_but_typed_command_is_removed(client):
    await client.callback("run:coin:free:2", mid=100, illustrated=True)
    assert requests(client, "sendMessage")[-1].reply_markup is None
    assert not requests(client, "deleteMessage")
    command_seen.clear()
    message = client.message(text=".calc 7*6")
    await client.feed(message=message)
    assert requests(client, "deleteMessage")[-1].message_id == message["message_id"]
    assert "42" in texts(client)[-1]


async def test_delete_sent_right_does_not_allow_deleting_human_command(client):
    await connect(client, delete=False)
    await client.feed(business_message=incoming(client, ".calc 7*6", sender=42))
    assert "42" in texts(client)[-1]
    assert not requests(client, "deleteBusinessMessages")


async def test_photo_with_command_caption_is_preserved(client, monkeypatch, tmp_path):
    monkeypatch.setattr(access, "settings", replace(access.settings, admin_ids=frozenset({42})))
    source = tmp_path / "source.png"
    Image.new("RGB", (320, 160), "orange").save(source)
    monkeypatch.setattr(wm, "download_file", AsyncMock(return_value=str(source)))
    await client.feed(message=client.message(photo=photo(), caption=".wm --count 1 Тест"))
    assert requests(client, "sendDocument")
    assert not requests(client, "deleteMessage")


async def test_button_parameters_wait_for_new_photo_and_back_cancels_that_wait(client, monkeypatch, tmp_path):
    monkeypatch.setattr(access, "settings", replace(access.settings, admin_ids=frozenset({42})))
    source = tmp_path / "source.png"
    Image.new("RGB", (320, 160), "orange").save(source)
    download = AsyncMock(return_value=str(source))
    monkeypatch.setattr(wm, "download_file", download)
    await client.feed(message=client.message(photo=photo()))
    await client.callback("run:wm:plus:0", mid=100, illustrated=True)
    await client.send("Тест")
    download.assert_not_awaited()
    prompt = requests(client, "sendMessage")[-1]
    assert "Отправьте фото" in prompt.text
    from aeniaflow.core.navigation import tool_return

    assert buttons(prompt)[0].callback_data == tool_return("wm")
    await client.callback(buttons(prompt)[0].callback_data)
    await client.feed(message=client.message(photo=photo()))
    download.assert_not_awaited()
    await client.callback("run:wm:plus:0", mid=100, illustrated=True)
    await client.send("Тест")
    await client.feed(message=client.message(photo=photo()))
    output = requests(client, "sendDocument")[-1]
    assert Image.open(BytesIO(output.document.data)).size == (320, 160)


async def test_afk_has_plain_prompt_and_button_to_turn_off(client, repository):
    await client.callback("run:afk:free:3", illustrated=True)
    await client.send("На встрече")
    assert repository.get_user(42)["afk_reason"] == "На встрече"
    await client.callback("run:afk:free:3", illustrated=True)
    await client.callback("afk:off", illustrated=True)
    assert not repository.get_user(42)["afk_reason"]
    assert "снова на связи" in last_panel(client).media.caption


async def test_page_indicator_does_not_cancel_input(client):
    from aiogram.types import Message

    await client.callback("run:calc:free:0", illustrated=True)
    await client.callback("nav:page", illustrated=True)
    message = Message.model_validate(client.message(text="2+2"))
    assert pending_input(message)
    await client.feed(message=message.model_dump(mode="json"))
    assert "4" in texts(client)[-1]
