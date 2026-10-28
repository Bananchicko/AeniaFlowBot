from aeniaflow.handlers.commands.media_tools import convert


async def handle(message, args, bot):
    try:
        rate = float(args or "1.5")
    except ValueError as exc:
        raise ValueError("Укажите числовой коэффициент скорости.") from exc
    if not 0.5 <= rate <= 2.0:
        raise ValueError("Коэффициент: от 0.5 до 2.0.")
    await convert(message, bot, "speed", rate)
