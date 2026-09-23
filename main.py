"""
Radnoy Content Bot
-------------------
Belgilangan vaqtlarda Supabase'dagi kontent-bankdan navbatdagi postni oladi,
adminga (DM orqali) tasdiqlash uchun yuboradi, admin tasdiqlasa
@radnoy_trener kanaliga majburiy imzo bilan joylaydi.
"""

import logging
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

import config
import db

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

TZ = ZoneInfo(config.TIMEZONE)


def build_full_text(body: str) -> str:
    return f"{body}\n\n{config.FOOTER_TEXT}"


def approval_keyboard(post_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Tasdiqlash", callback_data=f"approve:{post_id}"),
                InlineKeyboardButton("❌ Rad etish", callback_data=f"reject:{post_id}"),
            ]
        ]
    )


async def send_draft_for_approval(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Scheduled job: pick next queued post and DM it to the admin."""
    if not config.ADMIN_CHAT_ID:
        logger.warning("ADMIN_CHAT_ID sozlanmagan, post yuborilmadi.")
        return

    post = db.get_next_post_for_approval()
    if not post:
        await context.bot.send_message(
            chat_id=config.ADMIN_CHAT_ID,
            text="⚠️ Kontent-bankda navbatda turgan post qolmadi. Yangi postlar qo'shing.",
        )
        return

    db.mark_sent_for_approval(post["id"])
    preview = build_full_text(post["post_text"])
    await context.bot.send_message(
        chat_id=config.ADMIN_CHAT_ID,
        text=(
            f"🆕 Yangi post tasdiq kutmoqda (mavzu: {post['topic_tag']})\n\n"
            f"{preview}"
        ),
        reply_markup=approval_keyboard(post["id"]),
    )


async def handle_approval_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    action, post_id_str = query.data.split(":")
    post_id = int(post_id_str)
    post = db.get_post(post_id)

    if not post:
        await query.edit_message_text("Bu post topilmadi (o'chirilgan bo'lishi mumkin).")
        return

    if post["status"] == "published":
        await query.answer("Bu post allaqachon kanalga joylangan.", show_alert=True)
        return
    if post["status"] == "rejected":
        await query.answer("Bu post allaqachon rad etilgan.", show_alert=True)
        return

    if action == "approve":
        full_text = build_full_text(post["post_text"])
        sent = await context.bot.send_message(chat_id=config.CHANNEL_ID, text=full_text)
        db.mark_published(post_id, sent.message_id)
        await query.edit_message_text(f"✅ Kanalga joylandi:\n\n{full_text}")
    elif action == "reject":
        db.mark_rejected(post_id, notes="Admin tomonidan rad etildi")
        await query.edit_message_text(f"❌ Rad etildi:\n\n{build_full_text(post['post_text'])}")


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    await update.message.reply_text(
        "Salom! Bu Radnoy Content Bot.\n\n"
        f"Sizning shaxsiy chat ID'ingiz: `{chat_id}`\n\n"
        "Buni Render'dagi ADMIN_CHAT_ID muhit o'zgaruvchisiga qo'ying — "
        "shundan keyin bot tasdiqlash uchun postlarni shu yerga yuboradi.",
        parse_mode=ParseMode.MARKDOWN,
    )


async def cmd_queue(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if str(update.effective_chat.id) != str(config.ADMIN_CHAT_ID):
        return
    c = db.counts()
    await update.message.reply_text(
        "📊 Kontent-bank holati:\n"
        f"Navbatda: {c['queued']}\n"
        f"Tasdiq kutmoqda: {c['sent_for_approval']}\n"
        f"Rad etilgan: {c['rejected']}\n"
        f"Joylangan: {c['published']}"
    )


async def cmd_postnow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin buyrug'i bilan navbatdagi postni darhol tasdiqlashga yuborish (test uchun)."""
    if str(update.effective_chat.id) != str(config.ADMIN_CHAT_ID):
        return
    await send_draft_for_approval(context)


def parse_post_times() -> list[dtime]:
    times = []
    for part in config.POST_TIMES.split(","):
        part = part.strip()
        if not part:
            continue
        h, m = part.split(":")
        times.append(dtime(hour=int(h), minute=int(m), tzinfo=TZ))
    return times


def main() -> None:
    app = Application.builder().token(config.BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("queue", cmd_queue))
    app.add_handler(CommandHandler("postnow", cmd_postnow))
    app.add_handler(CallbackQueryHandler(handle_approval_callback))

    for t in parse_post_times():
        app.job_queue.run_daily(send_draft_for_approval, time=t)
        logger.info("Kunlik post vaqti sozlandi: %s", t)

    logger.info("Radnoy Content Bot ishga tushdi.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
