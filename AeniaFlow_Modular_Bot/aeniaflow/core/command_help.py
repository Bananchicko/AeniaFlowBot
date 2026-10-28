"""Copyable command examples shared by menus, input prompts and documentation."""

from html import escape
from aeniaflow.catalog import FEATURES

EXAMPLES = {
    "send": ".send 3 Привет!",
    "stop": ".stop",
    "chats": ".chats",
    "mutelist": ".mutelist",
    "watermark": ".watermark",
    "quote": ".quote Привет, мир!",
    "mute": ".mute",
    "unmute": ".unmute",
    "coin": ".coin",
    "msay": ".msay Привет!",
    "x": ".x",
    "print": ".print Привет!",
    "circle": ".circle AeniaFlow",
    "calc": ".calc (12+5)*3",
    "zalgo": ".zalgo Привет",
    "haha": ".haha 3",
    "rd": ".rd 1 100",
    "gif": ".gif",
    "afk": ".afk На встрече",
    "meme": ".meme Верх | Низ",
    "revo": ".revo",
    "speed": ".speed 1.5",
    "clock": ".clock Europe/Moscow",
    "timer": ".timer 5m",
    "profile": ".profile",
    "payments": ".payments",
    "settings": ".settings",
    "organizer": ".organizer",
    "note": ".note add Идея | Купить микрофон",
    "notes": ".notes",
    "todo": ".todo add Проверить звук",
    "remind": ".remind 30m Сделать перерыв",
    "reminders": ".reminders",
    "export": ".export",
    "delete_data": ".delete_data",
    "find": ".find фото",
    "status": ".status",
    "choose": ".choose чай | кофе",
    "dice": ".dice",
    "poll": ".poll Куда? | Парк | Кафе",
    "textstats": ".textstats Ваш текст",
    "encode": ".encode Привет",
    "decode": ".decode SGVsbG8=",
    "sha256": ".sha256 Привет",
    "uuid": ".uuid",
    "resize": ".resize 800",
    "rotate": ".rotate 90",
    "mirror": ".mirror",
    "fix": ".fix Текст с ошибками",
    "hint": ".hint Как подготовиться к встрече?",
    "leet": ".leet Привет",
    "dumb": ".dumb Привет",
    "clone": ".clone",
    "stt": ".stt",
    "voice": ".voice 1.2",
    "panic": ".panic 20",
    "words": ".words Привет как дела",
    "save": ".save",
    "tr": ".tr en Привет, мир!",
    "videonote": ".videonote",
    "blur": ".blur",
    "word": ".word",
    "guess": ".guess лампа",
    "gpt": ".gpt Объясни, как устроена радуга",
    "scam": ".scam https://example.com",
    "wm": ".wm alcLua",
    "summarize": ".summarize Текст для сокращения",
    "rewrite": ".rewrite Текст для редактирования",
    "explain": ".explain Фотосинтез",
    "audio": ".audio",
    "home": ".menu",
    "free": ".free",
    "plus": ".plus",
    "premium": ".premium",
    "help": ".help",
    "paysupport": ".paysupport",
    "connect": ".connect",
    "data": ".export",
    "terms": ".terms",
    "privacy": ".privacy",
    "tasks": ".todo",
    "search": ".find фото",
    "autoreply": ".autoreply text Привет! Отвечу позже.",
    "timezone": ".clock Europe/Moscow",
    "cooldown": ".autoreply cooldown 3600",
}
EXAMPLES.update(
    {
        "replies": ".replies",
        "replyadd": ".replyadd привет | Привет! Скоро отвечу.",
        "reply": ".reply привет",
        "replydel": ".replydel привет",
        "chatnote": ".chatnote Обсудить заказ",
        "chatinfo": ".chatinfo",
        "chatauto": ".chatauto Сейчас занят, скоро отвечу.",
        "pause": ".pause",
        "resume": ".resume",
        "read": ".read",
    }
)
EXAMPLES.update(
    {
        "tag": ".tag работа",
        "chatfind": ".chatfind работа",
        "later": ".later 30m Привет!",
        "outbox": ".outbox",
        "rules": ".rules",
        "ruleadd": ".ruleadd цена | Прайс пришлю сегодня",
        "ruledel": ".ruledel 1",
        "autoread": ".autoread on",
        "chatstats": ".chatstats",
        "antimute": ".antimute Привет!",
        "ref": ".ref",
    }
)
assert set(FEATURES) <= EXAMPLES.keys()


def command_hint(code):
    example = EXAMPLES.get(code, f".{code}")
    return f"<b>Команда:</b> <code>{escape(example)}</code>"


def with_command(text, code):
    """Put the command next to the heading, without adding another navigation step."""
    heading, separator, rest = text.partition("\n\n")
    return heading + "\n" + command_hint(code) + ("\n\n" + rest if separator else "")
