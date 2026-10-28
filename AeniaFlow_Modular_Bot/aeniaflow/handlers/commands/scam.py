from aeniaflow.core.responses import respond
import html, re
from aiogram import Bot
from aiogram.types import Message
from aeniaflow.core.helpers import message_text


async def handle(message: Message, args: str, bot: Bot):
    source = args or message_text(message)
    links = re.findall(r"https?://\S+|t\.me/\S+|www\.\S+", source, re.I)
    if not links:
        await respond(
            message, "Ссылок не найдено. Это простая локальная эвристика, а не проверка базы угроз."
        )
        return
    out = []
    for link in links[:8]:
        low = link.lower()
        reasons = []
        if re.search(r"\d{5,}", low):
            reasons.append("много цифр в ссылке")
        if any(
            t in low
            for t in ["airdrop", "wallet-connect", "freegift", "claim-prize", "verify-account", "seedphrase"]
        ):
            reasons.append("похоже на фишинговую приманку")
        if low.count("-") >= 4:
            reasons.append("подозрительно много дефисов")
        out.append(
            f'• {html.escape(link[:180])}: {", ".join(reasons) if reasons else "явных признаков по простым правилам нет"}'
        )
    await respond(
        message,
        "<b>Предварительная оценка ссылок</b>\n"
        + "\n".join(out)
        + "\n\nНе вводите пароли, коды входа или seed-фразы на неизвестных сайтах.",
    )
