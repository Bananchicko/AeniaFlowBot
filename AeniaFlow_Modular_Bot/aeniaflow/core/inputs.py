"""Short-lived input sessions scoped to actor, chat, topic and Business connection."""

from time import monotonic
from aeniaflow.core.runtime import BoundedCache

recent_media = BoundedCache(1000)
pending_inputs = BoundedCache(1000)
TTL = 600
MEDIA_COMMANDS = {
    "blur": "photo",
    "wm": "photo",
    "videonote": "video",
    "audio": "video",
    "stt": "audio",
    "save": "any",
}
MEDIA_NAMES = {
    "photo": "фото",
    "video": "видео",
    "audio": "аудио или голосовое",
    "av": "аудио, голосовое или видео",
    "any": "файл",
}


def input_key(message, user_id=None):
    return (
        getattr(message, "business_connection_id", None),
        message.chat.id,
        getattr(message, "message_thread_id", None),
        user_id or message.from_user.id,
    )


def media_file(message, kind="any"):
    if not message:
        return None
    fields = {
        "photo": ("photo",),
        "video": ("video", "animation", "video_note"),
        "audio": ("audio", "voice"),
        "av": ("video", "animation", "video_note", "audio", "voice"),
        "any": ("photo", "video", "animation", "video_note", "audio", "voice", "sticker", "document"),
    }
    for field in fields[kind]:
        value = getattr(message, field, None)
        if value:
            return value[-1] if field == "photo" else value
    document = getattr(message, "document", None)
    mime = (getattr(document, "mime_type", None) or "").lower()
    prefixes = {
        "photo": ("image/",),
        "video": ("video/",),
        "audio": ("audio/",),
        "av": ("audio/", "video/"),
        "any": ("",),
    }
    return document if document and mime.startswith(prefixes[kind]) else None


def remember_media(message, user_id=None):
    if media_file(message):
        recent_media[input_key(message, user_id)] = (monotonic(), message)


def media_source(message, kind="any"):
    # Attached media always wins over old media. Reply remains optional compatibility.
    if media_file(message):
        return message if media_file(message, kind) else None
    reply = getattr(message, "reply_to_message", None)
    if reply:
        return reply if media_file(reply, kind) else None
    if not getattr(message, "from_user", None) or not getattr(message, "chat", None):
        return None
    entry = recent_media.get(input_key(message))
    if entry and monotonic() - entry[0] < TTL:
        return entry[1] if media_file(entry[1], kind) else None
    return None


def begin_input(message, command, prefix="", user_id=None, mode="auto", back=None):
    pending_inputs[input_key(message, user_id)] = (monotonic(), command, prefix, mode, back)


def pending_input(message):
    key = input_key(message)
    item = pending_inputs.get(key)
    if item and monotonic() - item[0] < TTL:
        return item[1:]
    pending_inputs.pop(key, None)
    return None


def clear_input(message, user_id=None):
    pending_inputs.pop(input_key(message, user_id), None)
