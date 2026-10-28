from config import settings

FREE_FEATURES = [
    ("send", "Серия сообщений", ".send 3 Привет — повторить; .send Первое | Второе — разные сообщения"),
    ("chats", "Мои диалоги", ".chats — выбрать собеседника кнопкой"),
    ("mutelist", "Активные муты", ".mutelist — управление мутами в ЛС"),
    ("watermark", "Настройки водяных знаков", ".watermark — количество, расположение, стиль и прозрачность"),
    ("quote", "Цитата", ".quote Текст цитаты"),
    ("mute", "Мут", ".mute — бессрочный мут текущего собеседника; снять кнопкой «Размутить»"),
    ("unmute", "Снять мут", ".unmute — прекратить удаление входящих текущего собеседника"),
    ("coin", "Монетка", ".coin"),
    ("msay", "Текст в голосовое", ".msay Привет! — голосовое OGG/Opus; нужны gTTS и FFmpeg"),
    ("x", "Крестики-нолики", ".x — партия с ботом"),
    ("print", "Текст в картинку", ".print текст"),
    ("calc", "Калькулятор", ".calc (12+5)*3"),
    ("zalgo", "Глитч-текст", ".zalgo текст"),
    ("haha", "Генератор смеха", ".haha 3"),
    ("rd", "Случайное число", ".rd 1 100"),
    ("afk", "AFK-режим", ".afk причина — автоответ в ЛС; .afk off — выключить"),
    ("revo", "Случайная мини-игра", ".revo"),
    ("clock", "Часовой пояс", ".clock Europe/Moscow"),
    ("timer", "Таймер", ".timer 30s или .timer 5m — сохраняется после перезапуска"),
    ("profile", "Мой кабинет", ".profile — подписка и часовой пояс"),
    ("payments", "История платежей", ".payments — ваши покупки и чеки"),
    ("settings", "Настройки", ".settings — часовой пояс и данные"),
    ("organizer", "Органайзер", ".organizer — заметки, задачи, напоминания"),
    ("note", "Записать заметку", ".note add Идея | Текст; .note ID; .note delete ID"),
    ("notes", "Мои заметки", ".notes [страница]; .note find запрос"),
    ("todo", "Задачи", ".todo add Задача; .todo done ID; .todo undo ID; .todo delete ID"),
    ("remind", "Напоминание", ".remind 2h30m Текст; .remind every 1d Текст"),
    ("reminders", "Мои напоминания", ".reminders; .reminders cancel ID"),
    ("export", "Экспорт данных", ".export — JSON с вашими записями"),
    ("delete_data", "Удаление данных", ".delete_data — удалить личные записи с подтверждением"),
    ("find", "Поиск функций", ".find фото — поиск по каталогу"),
    ("status", "Состояние бота", ".status — доступность интеграций"),
    ("choose", "Случайный выбор", ".choose чай | кофе | вода"),
    ("dice", "Игровые кубики", ".dice; .dice dart; .dice basket; .dice ball"),
    ("poll", "Опрос", ".poll Вопрос | Вариант 1 | Вариант 2"),
    ("textstats", "Статистика текста", ".textstats Ваш текст"),
    ("encode", "Кодировать Base64", ".encode текст"),
    ("decode", "Декодировать Base64", ".decode SGVsbG8="),
    ("sha256", "Хеш SHA-256", ".sha256 текст"),
    ("uuid", "Генератор UUID", ".uuid"),
    ("replies", "Быстрые ответы", ".replies — список сохранённых ответов"),
    ("replyadd", "Сохранить ответ", ".replyadd привет | Привет! Скоро отвечу."),
    ("reply", "Отправить быстрый ответ", ".reply привет — отправить сохранённый текст"),
    ("replydel", "Удалить быстрый ответ", ".replydel привет"),
    ("chatnote", "Заметка о собеседнике", ".chatnote текст; .chatnote off — удалить пометку"),
    ("chatinfo", "Карточка диалога", ".chatinfo — мут, автоответ и настройки этого диалога"),
    ("chatauto", "Автоответ собеседнику", ".chatauto текст; .chatauto off — выключить"),
    ("pause", "Пауза в диалоге", ".pause — приостановить обработку этого ЛС"),
    ("resume", "Возобновить диалог", ".resume — снова обрабатывать этот ЛС"),
    ("read", "Прочитать входящие", ".read — отметить последнее входящее прочитанным"),
]

PREMIUM_FEATURES = [
    ("fix", "Исправление текста", ".fix Текст для исправления"),
    ("hint", "ИИ-подсказка", ".hint вопрос — нужен подключённый ИИ"),
    ("leet", "Стиль 1337", ".leet текст"),
    ("dumb", "Случайный регистр", ".dumb текст"),
    ("stt", "Голос в текст", ".stt — отправьте голосовое или аудио; нужен подключённый ИИ"),
    (
        "panic",
        "Очистка сообщений",
        ".panic 20 — удалить последние 20 сообщений текущего диалога, полученные ботом за сутки",
    ),
    ("save", "Копия медиа", ".save — отправьте медиа без защиты от копирования"),
    ("tr", "Перевод", ".tr en текст — нужен подключённый ИИ"),
    ("videonote", "Видео в кружок", ".videonote — отправьте видео; кружок до 60 секунд"),
    ("blur", "Размытие фото", ".blur — отправьте фото"),
    ("word", "Wordle", ".word — начать игру"),
    ("guess", "Попытка Wordle", ".guess слово"),
    ("gpt", "ИИ-помощник", ".gpt вопрос — нужен подключённый ИИ"),
    ("scam", "Оценка ссылок", ".scam ссылка — локальные признаки риска, без проверки сайта"),
    ("wm", "Водяные знаки", ".wm --count 5 Текст — несколько подписей; .watermark — настройки"),
    ("summarize", "Краткое содержание", ".summarize Текст для краткого пересказа"),
    ("rewrite", "Редактор текста", ".rewrite Текст для редактирования"),
    ("explain", "Простое объяснение", ".explain тема"),
    ("audio", "Извлечь звук", ".audio — отправьте видео; звук до 3 минут"),
]
FREE_FEATURES += [
    ("ref", "Пригласить друзей", ".ref — ссылка, начисления и заявки на выплату"),
    ("tag", "Метки диалогов", ".tag работа; .tag off — удалить метку"),
    ("chatfind", "Поиск диалогов", ".chatfind имя или метка — найти собеседника"),
]
PREMIUM_FEATURES += [
    ("antimute", "Текст через бота", ".antimute текст — одно сообщение через бота с удалением ввода"),
    ("later", "Отложенное сообщение", ".later 30m Привет — одна отправка через 30 минут"),
    ("outbox", "Очередь сообщений", ".outbox; .outbox cancel номер — отменить отправку"),
    ("rules", "Ответы по ключевым словам", ".rules — правила текущего или выбранного диалога"),
    ("ruleadd", "Добавить правило", ".ruleadd цена | Пришлю прайс сегодня"),
    ("ruledel", "Удалить правило", ".ruledel номер"),
    ("autoread", "Автоматическое прочтение", ".autoread on; .autoread off — для выбранного ЛС"),
    ("chatstats", "Статистика диалога", ".chatstats — входящие и исходящие, замеченные ботом"),
]
FEATURES = {code: (name, usage) for code, name, usage in FREE_FEATURES + PREMIUM_FEATURES}
PREMIUM_CODES = {code for code, _, _ in PREMIUM_FEATURES}

PLANS = {
    "day": {"days": 1, "stars": settings.day_stars, "label": "1 день"},
    "three_days": {"days": 3, "stars": settings.three_days_stars, "label": "3 дня"},
    "week": {"days": 7, "stars": settings.week_stars, "label": "7 дней"},
    "fortnight": {"days": 14, "stars": settings.fortnight_stars, "label": "14 дней"},
    "month": {"days": 30, "stars": settings.month_stars, "label": "30 дней"},
    "quarter": {"days": 90, "stars": settings.quarter_stars, "label": "90 дней"},
    "halfyear": {"days": 180, "stars": settings.halfyear_stars, "label": "180 дней"},
    "year": {"days": 365, "stars": settings.year_stars, "label": "365 дней"},
}
for _plan in PLANS.values():
    _plan["title"] = "AeniaFlow+ · " + _plan["label"]


CATEGORIES = {
    "media": (
        "Фото и медиа",
        (
            "msay",
            "print",
            "circle",
            "gif",
            "meme",
            "speed",
            "voice",
            "videonote",
            "blur",
            "wm",
            "watermark",
            "resize",
            "rotate",
            "mirror",
            "audio",
            "save",
        ),
    ),
    "ai": ("ИИ и перевод", ("gpt", "hint", "tr", "stt", "fix", "summarize", "rewrite", "explain")),
    "text": (
        "Текст и утилиты",
        (
            "quote",
            "calc",
            "zalgo",
            "haha",
            "leet",
            "dumb",
            "words",
            "send",
            "stop",
            "textstats",
            "encode",
            "decode",
            "sha256",
            "uuid",
            "scam",
        ),
    ),
    "games": ("Игры и выбор", ("coin", "x", "rd", "revo", "word", "guess", "choose", "dice", "poll")),
    "organizer": (
        "Заметки и дела",
        ("organizer", "note", "notes", "todo", "remind", "reminders", "timer", "clock"),
    ),
    "dialogs": ("Личные чаты", ("chats", "mute", "unmute", "mutelist", "afk", "panic", "clone")),
    "account": (
        "Аккаунт",
        ("profile", "payments", "settings", "export", "delete_data", "find", "status"),
    ),
}

CATEGORIES = {
    key: (title, tuple(code for code in codes if code in FEATURES))
    for key, (title, codes) in CATEGORIES.items()
}

CATEGORIES["dialogs"] = (
    CATEGORIES["dialogs"][0],
    CATEGORIES["dialogs"][1]
    + (
        "replies",
        "replyadd",
        "reply",
        "replydel",
        "chatnote",
        "chatinfo",
        "chatauto",
        "pause",
        "resume",
        "read",
        "tag",
        "chatfind",
        "antimute",
        "later",
        "outbox",
        "rules",
        "ruleadd",
        "ruledel",
        "autoread",
        "chatstats",
    ),
)
CATEGORIES["account"] = (CATEGORIES["account"][0], CATEGORIES["account"][1] + ("ref",))
