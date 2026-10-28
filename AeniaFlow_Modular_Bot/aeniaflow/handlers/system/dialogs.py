"""Select known conversations by name; Telegram IDs stay out of the user flow."""

from aeniaflow.core.runtime import db
from aeniaflow.core.helpers import esc
from aeniaflow.core.ui import panel
from aeniaflow.core.command_help import with_command
from aeniaflow.keyboards import kb


def rights_text(connection):
    if not connection:
        return "Business: событие подключения ещё не получено"
    return (
        f"Business: {'подключён' if connection['is_enabled'] else 'отключён'}\n"
        f"Ответы: {'разрешены' if connection['can_reply'] else 'нет права'}\n"
        f"Удаление входящих: {'разрешено' if connection['can_delete_all_messages'] else 'нет права'}"
    )


async def show_dialogs(message, owner, page=1, *, muted=False, edit=False):
    page = max(1, min(1000, int(page)))
    connection = db.get_connection(owner)
    rows = db.dialogs(owner, (page - 1) * 8, muted)
    text = f"<b>{'Муты' if muted else 'Чаты'}</b>\n\n"
    text += (
        "Выберите собеседника, чтобы снять мут."
        if muted and rows
        else (
            "Выберите собеседника, чтобы управлять мутом."
            if rows
            else (
                "Сейчас никто не заглушён."
                if muted
                else "Чаты появятся после новых сообщений в подключённых диалогах."
            )
        )
    )
    if not connection or not connection["is_enabled"]:
        text += "\n\nСтатус подключения и инструкция — в «Подключении»."
    text += "\n\nВ диалоге: <code>.mute</code> — включить,\n<code>.unmute</code> — снять. Мут без срока."
    entries = [
        (("● " if row["muted"] else "") + row["peer_name"][:24], f"dialog:open:{row['id']}") for row in rows
    ]
    buttons = [entries[i : i + 2] for i in range(0, len(entries), 2)]
    section = "mutelist" if muted else "chats"
    nav = []
    if page > 1:
        nav.append(("‹ Назад", f"page:{section}:{page-1}"))
    if db.dialogs(owner, page * 8, muted):
        nav.append(("Дальше ›", f"page:{section}:{page+1}"))
    buttons += [
        nav,
        [
            ("Все чаты", "menu:chats", "primary" if not muted else None),
            ("Муты", "menu:mutelist", "primary" if muted else None),
        ],
        [("Обновить", f"page:{section}:{page}"), ("Подключение", "menu:connect")],
        [("‹ Профиль", "menu:profile")],
    ]
    await panel(
        message, with_command(text, section), kb(buttons), edit=edit, art="dialogs", protect_content=True
    )


async def show_dialog(message, owner, identifier, *, edit=True):
    row = db.dialog(owner, identifier)
    if not row:
        raise ValueError("Диалог недоступен. Откройте .chats заново.")
    connection = db.connection_owner(row["connection_id"])
    connected = bool(connection and connection["is_enabled"] and connection["owner_id"] == owner)
    muted = bool(row["muted"])
    state = "Мут включён · без срока" if muted else "Мут выключен"
    text = f"<b>{esc(row['peer_name'])}</b>\n\n{state}\n"
    if not connected:
        text += "Это подключение отключено. Мут сейчас не действует.\n"
    if muted and row["mute_error"]:
        text += f"Удаление не работает: {esc(row['mute_error'])}\n"
    text += "\nМут автоматически удаляет новые входящие. Это не отключение уведомлений. Удалённые сообщения не восстанавливаются."
    text += "\n\nКоманды: <code>.mute</code> · <code>.unmute</code>\n<code>.chatinfo</code> · <code>.chatnote текст</code>\n<code>.chatauto текст</code> · <code>.pause</code> · <code>.resume</code>"
    text += "\nОбработка: " + ("пауза" if row["paused"] else "включена")
    text += "\nПерсональный автоответ: " + ("включён" if row["reply_text"] else "выключен")
    if row["note"] and not message.business_connection_id:
        text += "\n\nВаша пометка: " + esc(row["note"])
    if row["tag"]:
        text += "\nМетка: " + esc(row["tag"])
    rows = [
        [("Метка", f"chattool:tag:{identifier}"), ("Статистика", f"chattool:chatstats:{identifier}")],
        [("Отложить сообщение", f"chattool:later:{identifier}"), ("Очередь", "use:outbox")],
        [
            ("Ответы по словам", f"chattool:rules:{identifier}"),
            ("Автопрочтение", f"chattool:autoread:{identifier}"),
        ],
    ]
    if muted:
        rows.append([("Размутить", f"dialog:unmute:{identifier}", "success")])
    elif connected:
        rows.append([("Замутить", f"dialog:mute:{identifier}", "danger")])
    rows += [
        [("Пометка", f"chattool:chatnote:{identifier}"), ("Автоответ", f"chattool:chatauto:{identifier}")],
        [
            (
                "Возобновить" if row["paused"] else "Пауза",
                f"chattool:{'resume' if row['paused'] else 'pause'}:{identifier}",
            ),
            ("Прочитать", f"chattool:read:{identifier}"),
        ],
    ]
    rows.append([("‹ Чаты", "menu:chats"), ("Профиль", "menu:profile")])
    await panel(message, text, kb(rows), edit=edit, art="dialogs", protect_content=True)
