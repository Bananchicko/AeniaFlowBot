from aeniaflow.handlers.commands.media_tools import convert


async def handle(message, args, bot):
    try:
        rate = float(args or "1.2")
    except ValueError as exc:
        raise ValueError("Укажите числовой коэффициент тембра.") from exc
    if not 0.7 <= rate <= 1.5:
        raise ValueError("Коэффициент: от 0.7 до 1.5.")
    await convert(message, bot, "voice", rate)
