from aeniaflow.core.runtime import db
from aeniaflow.core.ui import panel
from aeniaflow.keyboards import kb


async def referral(message, args, bot):
    user = message.from_user.id
    if message.business_connection_id:
        await message.answer("Реферальный баланс и ссылка доступны командой .ref в ЛС самого бота.")
        return
    me = await bot.get_me()
    count = db.conn.execute("SELECT COUNT(*) FROM referrals WHERE inviter_id=?", (user,)).fetchone()[0]
    balance = db.referral_balance(user) / 1000
    days = db.conn.execute(
        "SELECT COALESCE(SUM(days),0) FROM referral_rewards WHERE inviter_id=? AND revoked=0", (user,)
    ).fetchone()[0]
    text = f"<b>Приглашайте друзей</b>\n\nВаша ссылка:\nhttps://t.me/{me.username}?start=ref_{user}\n\nПриглашено: {count}\nДоступно к выплате: {balance:g} Stars\nНачислено дней Plus: {days}\n\n50% от каждой покупки друга на срок от 30 дней. За каждую покупку от 100 Stars — ещё 1 день Plus за каждые полные 25 Stars.\n\nЗдесь учитывается вознаграждение внутри бота. Выплату проводит администратор вручную по заявке; это не баланс вашего Telegram. Возврат покупки отменяет награду. Ссылка учитывается только при первом входе друга."
    await panel(
        message,
        text,
        kb(
            [
                [("Запросить выплату", "ref:payout")],
                [("История заявок", "ref:history")],
                [("‹ Профиль", "menu:profile")],
            ]
        ),
    )


async def callback(query, bot):
    if query.message.business_connection_id:
        await query.answer("Откройте .ref в ЛС бота.", show_alert=True)
        return
    user = query.from_user.id
    if query.data == "ref:payout":
        balance = max(0, db.referral_balance(user) // 1000)
        await query.answer()
        await panel(
            query.message,
            f"Создать заявку на выплату {balance} Stars?\nАдминистратор проводит выплату вручную.",
            kb([[("Создать заявку", "ref:confirm"), ("Отмена", "use:ref")]]),
            edit=True,
        )
    elif query.data == "ref:confirm":
        identifier = db.request_payout(user)
        await query.answer("Заявка создана.", show_alert=True)
        await panel(
            query.message,
            f"Заявка #{identifier} создана. Статус: ожидает администратора.",
            kb([[("История", "ref:history"), ("‹ Профиль", "menu:profile")]]),
            edit=True,
        )
    else:
        rows = db.conn.execute(
            "SELECT * FROM referral_payouts WHERE user_id=? ORDER BY id DESC LIMIT 15", (user,)
        ).fetchall()
        names = {"pending": "ожидает", "paid": "администратор отметил выплату", "rejected": "отклонена"}
        text = (
            "\n".join(f"#{r['id']} · {r['stars']} Stars · {names[r['state']]}" for r in rows)
            or "Заявок пока нет."
        )
        await query.answer()
        await panel(query.message, text, kb([[("‹ Рефералы", "use:ref")]]), edit=True)
