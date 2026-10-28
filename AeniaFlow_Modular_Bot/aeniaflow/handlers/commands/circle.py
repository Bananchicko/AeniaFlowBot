from aiogram import Bot
from aiogram.types import Message, BufferedInputFile
from aeniaflow.core.helpers import circular_text_image, message_text


async def handle(message: Message, args: str, bot: Bot):
    image = circular_text_image(args.strip() or message_text(message) or "AeniaFlow")
    await message.answer_photo(
        BufferedInputFile(image.getvalue(), filename="aeniaflow-circle.png"), caption="Текст по кругу"
    )
