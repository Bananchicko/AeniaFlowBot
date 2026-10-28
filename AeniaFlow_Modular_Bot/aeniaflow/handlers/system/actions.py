"""Button actions use the clicking human's identity, never the bot message sender."""

from aiogram.types import User
from aeniaflow.core.inputs import begin_input, MEDIA_COMMANDS, MEDIA_NAMES
from aeniaflow.core.navigation import tool_name, action_return
from aeniaflow.core.helpers import esc
from aeniaflow.core.command_help import command_hint
from aeniaflow.core.ui import panel, private_only
from aeniaflow.keyboards import kb

# command, initial arguments, optional prompt for the next ordinary message
ACTIONS = {
    "send": (
        "send",
        "",
        "Напишите количество и текст: 3 Привет!\nИли разные сообщения через |: Первое | Второе\nОт 1 до 50 сообщений с паузой 0,5 секунды; серия завершится автоматически. Между сериями — 5 секунд.",
    ),
    "find": ("find", "", "Что найти? Например: фото, голос, заметки."),
    "note": ("note", "add", "Напишите название и текст через |\nНапример: Идея | Собрать команду"),
    "todo": ("todo", "add", "Что нужно сделать? Напишите задачу одним сообщением."),
    "remind": (
        "remind",
        "",
        "Когда и о чём напомнить?\nНапример: 30m Сделать перерыв\nИли: every 1d Проверить задачи",
    ),
    "autoreply": ("autoreply", "text", "Отправьте новый текст автоответа, до 1000 символов."),
    "timezone": ("clock", "", "Отправьте часовой пояс. Например: Europe/Moscow или Asia/Almaty."),
    "cooldown": (
        "autoreply",
        "cooldown",
        "Интервал автоответов одному собеседнику в секундах: от 30 до 604800.",
    ),
}
for _code in (
    "gpt",
    "hint",
    "fix",
    "summarize",
    "rewrite",
    "explain",
    "quote",
    "print",
    "circle",
    "msay",
    "zalgo",
    "leet",
    "dumb",
    "words",
    "textstats",
    "encode",
    "decode",
    "sha256",
    "scam",
    "guess",
):
    ACTIONS[_code] = (_code, "", "Напишите текст или вопрос следующим сообщением.")
ACTIONS.update(
    {
        "calc": ("calc", "", "Введите выражение. Например: (12+5)*3"),
        "tr": ("tr", "", "Укажите язык и текст. Например: en Привет, мир!"),
        "choose": ("choose", "", "Напишите варианты через |. Например: чай | кофе"),
        "poll": ("poll", "", "Напишите вопрос и варианты через |. Например: Куда? | Парк | Кафе"),
        "timer": ("timer", "", "На сколько поставить таймер? Например: 5m или 30s."),
        "meme": ("meme", "", "Напишите верхнюю и нижнюю надпись через |. Затем отправьте фото."),
        "wm": ("wm", "", "Напишите текст водяного знака. Затем отправьте фото."),
        "resize": ("resize", "", "Укажите ширину от 64 до 2048. Затем отправьте фото."),
        "speed": ("speed", "", "Укажите скорость, например 1.5. Затем отправьте медиа."),
        "voice": ("voice", "", "Укажите коэффициент тембра, например 1.2. Затем отправьте аудио."),
        "afk": (
            "afk",
            "",
            "Напишите, почему вы отошли. Этот текст получит собеседник, когда вам напишет.\nНапример: На встрече, отвечу позже.",
        ),
    }
)
# Keep each prompt tied to the selected action instead of a generic input form.
for _code, _prompt in {
    "msay": "Напишите текст для голосового.\nНапример: Привет, буду через пять минут.",
    "quote": "Напишите текст цитаты.",
    "print": "Напишите текст, который нужно превратить в картинку.",
    "circle": "Напишите текст для круглой надписи.",
    "gpt": "Напишите свой вопрос или задачу для ИИ.",
    "hint": "Опишите ситуацию, в которой нужен совет.",
    "fix": "Пришлите текст — бот исправит ошибки.",
    "rewrite": "Пришлите текст, который нужно переписать.",
    "summarize": "Пришлите текст, который нужно сократить.",
    "explain": "Напишите тему, которую нужно объяснить простыми словами.",
    "scam": "Пришлите ссылку. Бот проверит её написание на признаки риска.",
    "guess": "Напишите одно слово для текущей партии Wordle.",
    "encode": "Напишите текст для кодирования в Base64.",
    "decode": "Пришлите строку Base64, которую нужно прочитать.",
    "sha256": "Напишите текст, для которого нужен SHA-256.",
    "textstats": "Пришлите текст для подсчёта слов и символов.",
    "words": "Напишите до 10 слов. Бот отправит каждое отдельным сообщением.",
    "zalgo": "Напишите текст для глитч-эффекта.",
    "leet": "Напишите текст для замены букв цифрами.",
    "dumb": "Напишите текст для случайного регистра букв.",
}.items():
    ACTIONS[_code] = (_code, "", _prompt)
for _code in (
    "coin",
    "x",
    "rd",
    "revo",
    "word",
    "dice",
    "uuid",
    "status",
    "clone",
    "blur",
    "gif",
    "videonote",
    "audio",
    "stt",
    "save",
    "mirror",
    "rotate",
    "notes",
    "reminders",
    "export",
    "delete_data",
    "profile",
    "payments",
    "settings",
    "organizer",
    "clock",
    "watermark",
    "chats",
    "mutelist",
    "haha",
    "stop",
):
    ACTIONS[_code] = (_code, "", None)


for _retired in [
    "circle",
    "clone",
    "gif",
    "meme",
    "mirror",
    "resize",
    "rotate",
    "speed",
    "stop",
    "voice",
    "words",
]:
    ACTIONS.pop(_retired, None)

ACTIONS.update(
    {
        "replyadd": (
            "replyadd",
            "",
            "Напишите название и ответ через |. Например: привет | Привет! Скоро отвечу.",
        ),
        "reply": ("reply", "", "Напишите название сохранённого ответа."),
        "replydel": ("replydel", "", "Напишите название ответа, который нужно удалить."),
        "replies": ("replies", "", None),
        **{
            code: (code, "", None) for code in ("chatnote", "chatinfo", "chatauto", "pause", "resume", "read")
        },
    }
)


from aeniaflow.handlers.commands.dialog_tools import DIALOG_COMMANDS

ACTIONS.update({code: (code, "", None) for code in DIALOG_COMMANDS | {"outbox"}})
ACTIONS["ref"] = ("ref", "", None)
ACTIONS["antimute"] = (
    "antimute",
    "",
    "Отправьте текст одного сообщения. В Business оно отправляется от вашего аккаунта через бота. Другие боты всё ещё могут его удалить.",
)
ACTIONS["chatfind"] = ("chatfind", "", "Введите имя, username или метку собеседника.")


async def start_action(message, bot, user: User, key, *, back=None):
    if not await private_only(message, user):
        return
    back = back or action_return(key)
    if key == "send":
        from aeniaflow.handlers.commands.message_series import choose_count

        await choose_count(message, user=user, edit=True)
        return
    if key in {"mute", "unmute", "panic"}:
        from aeniaflow.catalog import FEATURES

        if key in {"mute", "unmute"}:
            text = (
                "Включает бессрочное удаление новых входящих от собеседника. Снять можно кнопкой «Размутить»."
                if key == "mute"
                else "Прекращает удаление новых входящих от собеседника."
            )
            await panel(
                message,
                f"<b>{esc(tool_name(key))}</b>\n<code>.{key}</code>\n\n{text}\n\nВ подключённом ЛС команда применяется к текущему человеку. В боте можно выбрать диалог.",
                kb(
                    [
                        [
                            (
                                "Выполнить" if message.business_connection_id else "Выбрать собеседника",
                                f"muterun:{key}",
                                "primary",
                            )
                        ],
                        [("‹ Назад", back), ("Главное меню", "menu:home")],
                    ]
                ),
                edit=True,
            )
            return
        if message.business_connection_id:
            from aeniaflow.handlers.system.command_dispatcher import incoming_message

            request = message.model_copy(
                update={"from_user": user, "text": f".{key}", "caption": None, "photo": None}
            )
            if key in {"mute", "unmute"}:
                from aeniaflow.core.business_access import current_dialog
                from aeniaflow.handlers.system.mutes import enable_mute, disable_mute

                row = current_dialog(request)
                await (enable_mute(bot, row) if key == "mute" else disable_mute(bot, row))
            else:
                await incoming_message(request, bot, from_button=True)
            return

        if key in {"mute", "unmute"}:
            from aeniaflow.handlers.system.dialogs import show_dialogs

            await show_dialogs(message, user.id, muted=key == "unmute", edit=True)
            return
        await panel(
            message,
            f"<b>{esc(tool_name(key))}</b>\n\nОтправьте команду в нужном личном диалоге:\n<code>{esc(FEATURES[key][1])}</code>\n\nЧаты и муты также доступны в профиле.",
            kb([[("Открыть чаты", "menu:chats")], [("‹ Назад", back), ("Главное меню", "menu:home")]]),
            edit=True,
        )
        return
    if key not in ACTIONS:
        raise ValueError("Откройте функции заново через .menu.")
    command, args, prompt = ACTIONS[key]
    from aeniaflow.handlers.system.command_dispatcher import SECTIONS
    from aeniaflow.handlers.system.sections import show_section

    if command in SECTIONS or command in {"notes", "reminders"}:
        await show_section(message, bot, user, SECTIONS.get(command, command), edit=True)
        return
    if prompt or command in MEDIA_COMMANDS:
        begin_input(message, command, args, user.id, mode="text" if prompt else "auto", back=back)
        prompt = prompt or f"Отправьте {MEDIA_NAMES[MEDIA_COMMANDS[command]]} следующим сообщением."
        names = {
            "find": "Поиск функций",
            "timezone": "Часовой пояс",
            "cooldown": "Интервал автоответа",
            "autoreply": "Текст автоответа",
        }
        rows = []
        if key == "wm":
            from aeniaflow.core.runtime import db
            from aeniaflow.handlers.system.watermarks import STYLES, SCATTERS, POSITIONS

            saved = db.get_user(user.id)
            placement = (
                POSITIONS[saved["watermark_position"]]
                if saved["watermark_count"] == 1
                else SCATTERS[saved["watermark_scatter"]]
            )
            prompt += f'\n\nСейчас: {saved["watermark_count"]} шт. · {STYLES[saved["watermark_style"]]} · {saved["watermark_opacity"]}%.\n{placement}.\nДругое количество: <code>.wm --count 8 alcLua</code>'
            rows.append([("Количество и стиль", "menu:watermark")])
        if key == "afk":
            rows.append([("Я вернулся · выключить", "afk:off", "success")])
        rows.append([("‹ Назад", back), ("Главное меню", "menu:home")])
        await panel(
            message,
            f"<b>{esc(names.get(key, tool_name(key)))}</b>\n{command_hint(key)}\n\n{prompt}\n\nКоманда работает и в боте, и в подключённом ЛС.\nЧтобы отменить ввод, нажмите «Назад».",
            kb(rows),
            edit=True,
        )
    else:
        from aeniaflow.handlers.system.command_dispatcher import incoming_message

        request = message.model_copy(
            update={
                "from_user": user,
                "text": f".{command} {args}".strip(),
                "caption": None,
                "reply_to_message": None,
                **{
                    kind: None
                    for kind in (
                        "photo",
                        "video",
                        "animation",
                        "audio",
                        "voice",
                        "document",
                        "video_note",
                        "sticker",
                    )
                },
            }
        )
        await incoming_message(request, bot, from_button=True)
