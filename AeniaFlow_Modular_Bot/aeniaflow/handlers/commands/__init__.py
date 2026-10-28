from aeniaflow.handlers.commands import (
    quote,
    coin,
    msay,
    x,
    print_text,
    circle,
    calc,
    zalgo,
    haha,
    rd,
    gif,
    afk,
    meme,
    revo,
    speed,
    online,
    fix,
    hint,
    leet,
    dumb,
    clone,
    clock,
    stt,
    voice,
    words,
    save,
    tr,
    videonote,
    blur,
    timer,
    word,
    guess,
    gpt,
    scam,
    wm,
)

COMMANDS = {
    "quote": quote.handle,
    "coin": coin.handle,
    "msay": msay.handle,
    "x": x.handle,
    "print": print_text.handle,
    "circle": circle.handle,
    "calc": calc.handle,
    "zalgo": zalgo.handle,
    "haha": haha.handle,
    "rd": rd.handle,
    "gif": gif.handle,
    "afk": afk.handle,
    "meme": meme.handle,
    "revo": revo.handle,
    "speed": speed.handle,
    "online": online.handle,
    "fix": fix.handle,
    "hint": hint.handle,
    "leet": leet.handle,
    "dumb": dumb.handle,
    "clone": clone.handle,
    "clock": clock.handle,
    "stt": stt.handle,
    "voice": voice.handle,
    "words": words.handle,
    "save": save.handle,
    "tr": tr.handle,
    "videonote": videonote.handle,
    "blur": blur.handle,
    "timer": timer.handle,
    "word": word.handle,
    "guess": guess.handle,
    "gpt": gpt.handle,
    "scam": scam.handle,
    "wm": wm.handle,
}

from aeniaflow.handlers.commands import (
    organizer,
    utilities,
    private_chats,
    ai_tools,
    media_tools,
    message_series,
)

COMMANDS.update(
    {
        "send": message_series.send,
        "mute": private_chats.mute,
        "unmute": private_chats.unmute,
        "panic": private_chats.panic,
        "note": organizer.note,
        "notes": organizer.notes,
        "todo": organizer.todo,
        "remind": organizer.remind,
        "reminders": organizer.reminders,
        "timer": organizer.timer,
        "export": organizer.export,
        "delete_data": organizer.delete_data,
        "find": utilities.find,
        "status": utilities.status,
        "choose": utilities.choose,
        "dice": utilities.dice,
        "poll": utilities.poll,
        "textstats": utilities.textstats,
        "encode": utilities.encode,
        "decode": utilities.decode,
        "sha256": utilities.sha256,
        "uuid": utilities.uuid,
        "gpt": ai_tools.gpt,
        "hint": ai_tools.hint,
        "summarize": ai_tools.summarize,
        "rewrite": ai_tools.rewrite,
        "explain": ai_tools.explain,
        "resize": media_tools.resize,
        "rotate": media_tools.rotate,
        "mirror": media_tools.mirror,
        "audio": media_tools.audio,
    }
)

# Retired commands are unavailable both from buttons and from typed input.
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
    COMMANDS.pop(_retired, None)

from aeniaflow.handlers.commands import dialog_tools

COMMANDS.update(dialog_tools.COMMANDS)

from aeniaflow.handlers.commands.chat_plus import antimute

COMMANDS["antimute"] = antimute

from aeniaflow.handlers.commands.referrals import referral

COMMANDS["ref"] = referral
