"""User directory, confirmed access changes and segmented broadcast drafts."""

import json
import time
from aeniaflow.core.runtime import db
from aeniaflow.core.access import admin_ids, is_owner
from aeniaflow.core.admin_repository import LIFETIME
from aeniaflow.core.ui import panel, format_time
from aeniaflow.core.helpers import esc
from aeniaflow.core.inputs import begin_input, clear_input
from aeniaflow.keyboards import kb

COMMANDS = {
    "users",
    "user",
    "giveplus",
    "takeplus",
    "banuser",
    "unbanuser",
    "adminsearch",
    "admincast",
    "adminchannel",
}
JOB_NAMES = {
    "draft": "черновик",
    "queued": "в очереди",
    "paused": "на паузе",
    "cancelled": "отменена",
    "finished": "завершена",
}
AUDIENCES = {"all": "Все", "free": "Бесплатные", "plus": "Plus", "banned": "Заблокированные"}


def user_query(audience="all", query="", *, mail=False):
    owners = admin_ids()
    placeholders = ",".join("?" for _ in owners) or "NULL"
    plus = f"(premium_until>? OR user_id IN ({placeholders}))"
    args = []
    where = ["1=1"]
    if audience in {"plus", "free"}:
        where.append(plus if audience == "plus" else "NOT " + plus)
        args.extend([int(time.time()), *owners])
    elif audience == "banned":
        where.append("banned=1")
    if query:
        where.append(
            "(CAST(user_id AS TEXT)=? OR CASEFOLD(username) LIKE ? ESCAPE '!' OR CASEFOLD(first_name) LIKE ? ESCAPE '!')"
        )
        needle = query.lstrip("@").casefold().replace("!", "!!").replace("%", "!%").replace("_", "!_")
        args.extend([query, "%" + needle + "%", "%" + needle + "%"])
    if mail:
        where.extend(["dm_started=1", "mail_enabled=1", "banned=0"])
    return " AND ".join(where), args


def recipients(audience):
    where, args = user_query(audience, mail=True)
    return [
        r[0] for r in db.conn.execute("SELECT user_id FROM users WHERE " + where + " ORDER BY user_id", args)
    ]


async def screen(message, text, rows, *, edit=True):
    await panel(
        message,
        text,
        kb(rows + [[("‹ Админ-панель", "admin:view:home")]]),
        edit=edit,
        protect_content=True,
        admin_only=True,
    )


async def directory(message, user, mode="all", page=0):
    if mode not in {*AUDIENCES, "search"}:
        return
    page = max(0, min(int(page), 100000))
    query = db.runtime_option(f"admin_search:{user.id}") if mode == "search" else ""
    where, args = user_query(mode, query)
    total = db.conn.execute("SELECT COUNT(*) FROM users WHERE " + where, args).fetchone()[0]
    page = min(page, max(0, (total - 1) // 8))
    rows = db.conn.execute(
        "SELECT * FROM users WHERE " + where + " ORDER BY last_seen DESC,user_id LIMIT 8 OFFSET ?",
        [*args, page * 8],
    ).fetchall()
    buttons = [
        [
            (
                (
                    "🚫 "
                    if r["banned"]
                    else "⭐ " if r["premium_until"] > time.time() or is_owner(r["user_id"]) else ""
                )
                + (r["first_name"] or r["username"] or str(r["user_id"]))
            )[:35],
            f"admin:person:{r['user_id']}",
        ]
        for r in rows
    ]
    buttons = [[(label, data)] for label, data in buttons]
    nav = []
    if page:
        nav.append(("‹", f"admin:users:{mode}:{page-1}"))
    if (page + 1) * 8 < total:
        nav.append(("›", f"admin:users:{mode}:{page+1}"))
    buttons += [
        nav,
        [("Все", "admin:users:all:0"), ("Plus", "admin:users:plus:0")],
        [("Бесплатные", "admin:users:free:0"), ("Бан", "admin:users:banned:0")],
        [("Поиск по ID / имени", "admin:search:open")],
    ]
    await screen(
        message,
        f"<b>Пользователи · {esc(AUDIENCES.get(mode,'Поиск'))}</b>\nНайдено: {total} · страница {page+1}\n\nВыберите пользователя.\n<code>.users имя</code> · <code>.user ID</code>",
        buttons,
    )


async def person(message, target, notice=""):
    row = db.get_user(target)
    if not row:
        raise ValueError("Пользователь не найден. Он должен сначала открыть бота или подключить Business.")
    plus = (
        "администратор · бесплатно"
        if is_owner(target)
        else (
            "бессрочно"
            if row["premium_until"] >= LIFETIME
            else format_time(row["premium_until"]) if row["premium_until"] > time.time() else "нет"
        )
    )
    text = f"<b>{esc(row['first_name'] or 'Пользователь')}</b>\nID: <code>{target}</code>\nUsername: {esc('@'+row['username'] if row['username'] else '—')}\nPlus: {plus}\nДоступ: {'заблокирован' if row['banned'] else 'разрешён'}\nЛС бота: {'открывал' if row['dm_started'] else 'не открывал'}\nРассылка: {'включена' if row['mail_enabled'] else 'отключена пользователем'}\nАктивность: {format_time(row['last_seen']) if row['last_seen'] else '—'}"
    if row["ban_reason"]:
        text += "\nПричина: " + esc(row["ban_reason"])
    if notice:
        text += "\n\n" + esc(notice)
    rows = []
    if not is_owner(target):
        rows += [
            [
                ("Выдать Plus", f"admin:grantpick:{target}"),
                ("Забрать Plus", f"admin:prepare:revoke:{target}:0"),
            ],
            [
                (
                    ("Разбанить" if row["banned"] else "Забанить"),
                    f"admin:prepare:{'unban' if row['banned'] else 'ban'}:{target}:0",
                )
            ],
        ]
    else:
        text += "\n\nАдминистратор защищён от бана и отзыва бесплатного Plus. Сначала снимите его роль в разделе администраторов."
    rows += [[("‹ Пользователи", "admin:users:all:0")]]
    await screen(message, text, rows)


async def prepare(message, user, action, target, days=0, reason=""):
    if action not in {"grant", "revoke", "ban", "unban"} or not db.get_user(target):
        raise ValueError("Действие или пользователь недоступны.")
    if is_owner(target):
        raise ValueError("Сначала снимите роль администратора. Владельца блокировать нельзя.")
    if action == "grant" and days not in {0, 7, 30, 90, 365}:
        raise ValueError("Недоступный срок Plus.")
    label = {
        "grant": f"Выдать Plus: {str(days)+' дней' if days else 'без срока'}",
        "revoke": "Забрать весь текущий Plus",
        "ban": "Заблокировать использование бота",
        "unban": "Снять блокировку",
    }[action]
    token = db.prepare_admin_action(user.id, action, {"target": target, "days": days, "reason": reason})
    extra = (
        "\nПлатёжные чеки сохраняются. Это не возврат Stars; новая покупка снова даст Plus."
        if action == "revoke"
        else ""
    )
    await screen(
        message,
        f"<b>Подтверждение</b>\n\n{label}\nПользователь: <code>{target}</code>{extra}",
        [[("Подтвердить", f"admin:confirm:{token}"), ("Отмена", f"admin:person:{target}")]],
    )


async def confirm(message, user, token):
    with db.atomic():
        row = db.admin_action(user.id, token)
        if not row:
            raise ValueError("Подтверждение уже использовано или истекло. Откройте пользователя заново.")
        data = json.loads(row["payload"])
        target = data["target"]
        if is_owner(target):
            raise ValueError("Пользователь стал администратором. Изменение отменено.")
        if row["action"] == "grant":
            db.grant_plus(user.id, target, data["days"])
        elif row["action"] == "revoke":
            db.revoke_plus(user.id, target)
        else:
            db.ban_user(user.id, target, row["action"] == "ban", data["reason"])
        db.conn.execute("UPDATE admin_actions SET used=1 WHERE token=?", (token,))
    await person(message, target, "Изменение применено.")


async def cast_view(message, user, identifier):
    job = db.broadcast(identifier)
    if not job:
        raise ValueError("Рассылка не найдена.")
    counts = db.broadcast_counts(identifier)
    text = f"<b>Рассылка #{identifier} · {AUDIENCES[job['audience']]}</b>\nСтатус: {esc(JOB_NAMES.get(job['state'], job['state']))}\n"
    rows = []
    if job["state"] == "draft":
        count = len(recipients(job["audience"]))
        text += (
            f"Получателей сейчас: {count}\n\n"
            + esc(job["body"])
            + "\n\nОтправка только в ЛС самого бота. При обслуживании очередь ждёт."
        )
        if job["actor"] == user.id:
            rows.append(
                [("Отправить", f"admin:castsend:{identifier}"), ("Отмена", f"admin:castcancel:{identifier}")]
            )
    else:
        text += "\n" + "\n".join(
            f"{label}: {counts.get(key,0)}"
            for key, label in [
                ("pending", "Ожидают"),
                ("sent", "Доставлено"),
                ("failed", "Ошибки"),
                ("skipped", "Пропущено"),
                ("uncertain", "Результат неизвестен"),
            ]
        )
        rows.append([("Обновить", f"admin:castview:{identifier}")])
        if job["state"] in {"queued", "paused"}:
            rows.append(
                [
                    (
                        "Продолжить" if job["state"] == "paused" else "Пауза",
                        f"admin:cast{'resume' if job['state']=='paused' else 'pause'}:{identifier}",
                    ),
                    ("Отменить остаток", f"admin:castcancel:{identifier}"),
                ]
            )
    rows.append([("‹ Рассылки", "admin:casts:all")])
    await screen(message, text, rows)


async def casts(message):
    jobs = db.conn.execute("SELECT * FROM broadcasts ORDER BY id DESC LIMIT 8").fetchall()
    rows = [
        [("Всем", "admin:castaud:all"), ("Plus", "admin:castaud:plus"), ("Бесплатным", "admin:castaud:free")]
    ]
    rows += [
        [(f"#{r['id']} · {AUDIENCES[r['audience']]} · {r['state']}", f"admin:castview:{r['id']}")]
        for r in jobs
    ]
    await screen(
        message,
        "<b>Рассылки</b>\n\nВыберите аудиторию, введите текст и проверьте предпросмотр. Заблокированные и отказавшиеся от рассылки пользователи исключаются. Бесплатная отправка с ограничением частоты.",
        rows,
    )


async def handle(message, args, bot, command):
    user = message.from_user
    if command in {"users", "adminsearch"}:
        clear_input(message)
        if args:
            db.set_runtime_option(f"admin_search:{user.id}", args[:100])
        await directory(message, user, "search" if args else "all")
    elif command == "user":
        if not args.isdigit():
            raise ValueError("Пример: .user 123456789")
        await person(message, int(args))
    elif command in {"giveplus", "takeplus", "banuser", "unbanuser"}:
        parts = args.split(maxsplit=1)
        if not parts or not parts[0].isdigit():
            raise ValueError(f"Пример: .{command} ID" + (" 30" if command == "giveplus" else ""))
        tail = parts[1] if len(parts) > 1 else ""
        if command == "giveplus" and tail not in {"7", "30", "90", "365", "0", "forever"}:
            raise ValueError("После ID укажите 7, 30, 90, 365 или forever.")
        await prepare(
            message,
            user,
            {"giveplus": "grant", "takeplus": "revoke", "banuser": "ban", "unbanuser": "unban"}[command],
            int(parts[0]),
            int(tail) if command == "giveplus" and tail.isdigit() else 0,
            tail if command == "banuser" else "",
        )
    elif command == "admincast":
        audience, _, body = args.partition(" ")
        identifier = db.new_broadcast(user.id, audience, body.strip())
        clear_input(message)
        await cast_view(message, user, identifier)
    elif command == "adminchannel":
        from config import normalize_channel

        channel = normalize_channel(args)
        if not isinstance(channel, str) or not channel.startswith("@"):
            raise ValueError("Укажите публичный канал: @username")
        me = await bot.get_me()
        member = await bot.get_chat_member(channel, me.id)
        if member.status not in {"administrator", "creator"}:
            raise ValueError("Сначала добавьте этого бота администратором канала.")
        db.set_runtime_option("required_channel", channel)
        db.audit(user.id, "required_channel", channel)
        clear_input(message)
        await screen(message, "Канал сохранён: " + esc(channel) + "\nPlus освобождён от подписки.", [])


async def payout_list(message):
    rows = db.conn.execute(
        "SELECT * FROM referral_payouts WHERE state='pending' ORDER BY id LIMIT 12"
    ).fetchall()
    text = "<b>Выплаты рефералам</b>\n\nВыплата проводится вручную вне бота. Кнопка ниже только фиксирует её после фактического перечисления."
    buttons = []
    for row in rows:
        text += f"\n\n#{row['id']} · пользователь {row['user_id']} · {row['stars']} Stars"
        buttons.append(
            [
                (f"Выплачено #{row['id']}", f"admin:payoutask:{row['id']}"),
                (f"Отклонить #{row['id']}", f"admin:payoutreject:{row['id']}"),
            ]
        )
    await screen(message, text if rows else text + "\n\nНет ожидающих заявок.", buttons)


async def callback(query, bot):
    message, user = query.message, query.from_user
    parts = query.data.split(":")
    action = parts[1]
    await query.answer()
    if action == "payouts":
        await payout_list(message)
    elif action in {"payoutask", "payoutreject"}:
        identifier = int(parts[2])
        token = db.prepare_admin_action(
            user.id, "payout_paid" if action == "payoutask" else "payout_reject", {"id": identifier}
        )
        text = (
            "Фактическая выплата уже проведена? Эта кнопка НЕ переводит Stars."
            if action == "payoutask"
            else "Отклонить заявку и освободить её баланс?"
        )
        await screen(
            message,
            text,
            [[("Подтвердить", f"admin:payoutconfirm:{token}"), ("Отмена", "admin:payouts:all")]],
        )
    elif action == "payoutconfirm":
        with db.atomic():
            row = db.admin_action(user.id, parts[2])
            if not row or row["action"] not in {"payout_paid", "payout_reject"}:
                raise ValueError("Подтверждение истекло или уже использовано.")
            db.resolve_payout(user.id, json.loads(row["payload"])["id"], row["action"] == "payout_paid")
            db.conn.execute("UPDATE admin_actions SET used=1 WHERE token=?", (parts[2],))
        await payout_list(message)
    elif action == "users":
        await directory(message, user, parts[2], int(parts[3]))
    elif action == "person":
        await person(message, int(parts[2]))
    elif action == "grantpick":
        target = int(parts[2])
        rows = [
            [(label, f"admin:prepare:grant:{target}:{days}") for days, label in pair]
            for pair in [
                [(7, "7 дней"), (30, "30 дней")],
                [(90, "90 дней"), (365, "365 дней")],
                [(0, "Без срока")],
            ]
        ]
        await screen(message, "<b>Выдать Plus</b>\nСрок добавляется к действующему доступу.", rows)
    elif action == "prepare":
        await prepare(message, user, parts[2], int(parts[3]), int(parts[4]))
    elif action == "confirm":
        await confirm(message, user, parts[2])
    elif action in {"search", "channel", "castaud"}:
        cmd = {"search": "adminsearch", "channel": "adminchannel", "castaud": "admincast"}[action]
        begin_input(
            message,
            cmd,
            parts[2] if action == "castaud" else "",
            user_id=user.id,
            mode="text",
            back="admin:view:home",
        )
        prompt = {
            "search": "Введите ID, username или часть имени пользователя.",
            "channel": "Пришлите @username канала. Бот должен быть его администратором.",
            "castaud": "Пришлите текст рассылки, до 3000 символов. Затем появится предпросмотр и подтверждение.",
        }[action]
        await screen(message, prompt, [])
    elif action == "casts":
        await casts(message)
    elif action == "castview":
        await cast_view(message, user, int(parts[2]))
    elif action == "castsend":
        identifier = int(parts[2])
        job = db.broadcast(identifier)
        if job:
            db.queue_broadcast(user.id, identifier, recipients(job["audience"]))
        await cast_view(message, user, identifier)
    elif action in {"castpause", "castresume", "castcancel"}:
        identifier = int(parts[2])
        state = {"castpause": "paused", "castresume": "queued", "castcancel": "cancelled"}[action]
        allowed_states = (
            ("queued",)
            if action == "castpause"
            else ("paused",) if action == "castresume" else ("draft", "queued", "paused")
        )
        with db.atomic():
            changed = db.conn.execute(
                "UPDATE broadcasts SET state=? WHERE id=? AND state IN ("
                + ",".join("?" for _ in allowed_states)
                + ")",
                [state, identifier, *allowed_states],
            ).rowcount
            if changed:
                db.audit(user.id, "broadcast_" + state, str(identifier))
        await cast_view(message, user, identifier)
