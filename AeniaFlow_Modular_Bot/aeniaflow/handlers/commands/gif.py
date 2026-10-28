from aeniaflow.handlers.commands.media_tools import convert


async def handle(message, args, bot):
    rate = 1.0
    await convert(message, bot, "gif", rate)
