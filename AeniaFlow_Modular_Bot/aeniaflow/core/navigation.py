"""Flat tool lists and stable return destinations for native Telegram buttons."""

from aeniaflow.catalog import FEATURES, PREMIUM_FEATURES, PREMIUM_CODES

PAGE_SIZE = 16
BASIC_CODES = (
    "tag",
    "chatfind",
    "mute",
    "unmute",
    "send",
    "replies",
    "msay",
    "print",
    "calc",
    "afk",
    "chatinfo",
    "chatnote",
    "chatauto",
    "read",
    "pause",
    "resume",
    "note",
    "remind",
    "replyadd",
    "reply",
    "replydel",
    "quote",
    "todo",
    "timer",
    "textstats",
    "choose",
    "coin",
    "rd",
    "dice",
    "x",
    "poll",
    "revo",
    "zalgo",
    "haha",
    "encode",
    "decode",
    "sha256",
    "uuid",
)

PLUS_CODES = (
    "antimute",
    "later",
    "outbox",
    "rules",
    "ruleadd",
    "ruledel",
    "autoread",
    "chatstats",
    "gpt",
    "tr",
    "fix",
    "rewrite",
    "summarize",
    "explain",
    "hint",
    "stt",
    "wm",
    "blur",
    "videonote",
    "audio",
    "save",
    "panic",
    "leet",
    "dumb",
    "word",
    "scam",
)
assert set(PLUS_CODES) == {code for code, _, _ in PREMIUM_FEATURES} - {"guess"}

SHORT_NAMES = {
    "mute": "Мут",
    "unmute": "Размут",
    "send": "Серия сообщений",
    "stop": "Остановить серию",
    "msay": "Текст в голос",
    "print": "Текст в фото",
    "circle": "Текст по кругу",
    "gif": "Видео в GIF",
    "meme": "Мем из фото",
    "rotate": "Повернуть фото",
    "mirror": "Отразить фото",
    "resize": "Размер фото",
    "textstats": "Статистика текста",
    "note": "Записать заметку",
    "todo": "Добавить задачу",
    "remind": "Напомнить мне",
    "x": "Крестики-нолики",
    "revo": "Мини-игра",
    "afk": "Я отошёл / AFK",
    "encode": "Текст → Base64",
    "decode": "Base64 → текст",
    "uuid": "Создать UUID",
    "gpt": "Спросить ИИ",
    "fix": "Исправить текст",
    "rewrite": "Переписать текст",
    "summarize": "Сократить текст",
    "explain": "Объяснить проще",
    "hint": "Дать совет",
    "stt": "Голос в текст",
    "blur": "Размыть фото",
    "voice": "Изменить голос",
    "panic": "Очистить диалог",
    "dumb": "Случайный регистр",
    "guess": "Ответ в Wordle",
}


def tool_name(code):
    return SHORT_NAMES.get(code, FEATURES.get(code, (code, ""))[0])


def tool_page(mode="free", page=0):
    codes = PLUS_CODES if mode == "plus" else BASIC_CODES
    total = (len(codes) + PAGE_SIZE - 1) // PAGE_SIZE
    page = max(0, min(int(page), total - 1))
    return codes[page * PAGE_SIZE : (page + 1) * PAGE_SIZE], page, total


def tool_return(code):
    mode = "plus" if code in PREMIUM_CODES else "free"
    codes = PLUS_CODES if mode == "plus" else BASIC_CODES
    page = codes.index(code) // PAGE_SIZE if code in codes else 0
    return f"list:{mode}:{page}"


def run_callback(code):
    if code not in BASIC_CODES and code not in PLUS_CODES:
        return f"use:{code}"
    return f"run:{code}:{tool_return(code).removeprefix('list:')}"


def action_return(key):
    return {
        "find": "list:free:0",
        "timezone": "menu:settings",
        "clock": "menu:settings",
        "autoreply": "menu:autoreply",
        "cooldown": "menu:autoreply",
        "note": "menu:notes",
        "todo": "menu:tasks",
        "remind": "menu:reminders",
        "wm": "menu:watermark",
    }.get(key, tool_return(key))
