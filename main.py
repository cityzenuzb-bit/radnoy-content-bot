"""
Radnoy Content Bot
-------------------
Belgilangan vaqtlarda Supabase'dagi kontent-bankdan navbatdagi postni oladi,
barcha adminlarga (DM orqali) tasdiqlash uchun yuboradi, admin tasdiqlasa
@radnoy_trener kanaliga majburiy imzo bilan joylaydi. Admin postni tahrirlashi
ham, boshqa adminlarga dostup berishi ham mumkin.
"""

import logging
import os
import threading
from datetime import datetime, time as dtime
from http.server import BaseHTTPRequestHandler, HTTPServer
from zoneinfo import ZoneInfo

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

import config
import db

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

TZ = ZoneInfo(config.TIMEZONE)

# chat_id -> post_id ning tahrirlanishini kutayotgan holati (xotirada saqlanadi)
pending_edits: dict[int, int] = {}


class _HealthCheckHandler(BaseHTTPRequestHandler):
    """Render 'web service' turi portga ulanishni talab qiladi. Bot faqat
    Telegram polling qiladi, real HTTP endpoint kerak emas, lekin Render'ning
    port-skanerini qondirish uchun minimal javob beruvchi server kerak —
    bo'lmasa Render deployni 'muvaffaqiyatsiz' deb belgilab, botni o'chirib
    qo'yadi."""

    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Radnoy Content Bot ishlamoqda.")

    def log_message(self, format, *args):
        pass  # Render loglarini keraksiz HTTP so'rovlar bilan to'ldirmaslik uchun


def start_health_server() -> None:
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), _HealthCheckHandler)
    logger.info("Health-check server %s portda ishga tushdi.", port)
    server.serve_forever()


def build_full_text(body: str) -> str:
    return f"{body}\n\n{config.FOOTER_TEXT}"


def approval_keyboard(post_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Tasdiqlash", callback_data=f"approve:{post_id}"),
                InlineKeyboardButton("❌ Rad etish", callback_data=f"reject:{post_id}"),
            ],
            [
                InlineKeyboardButton("✏️ Tahrirlash", callback_data=f"edit:{post_id}"),
            ],
        ]
    )


async def send_draft_for_approval(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Scheduled job: pick next queued post and DM it to all admins."""
    admin_ids = db.get_all_admin_chat_ids()
    if not admin_ids:
        logger.warning("Hech qanday admin sozlanmagan, post yuborilmadi.")
        return

    post = db.get_next_post_for_approval()
    if not post:
        for admin_id in admin_ids:
            try:
                await context.bot.send_message(
                    chat_id=admin_id,
                    text="⚠️ Kontent-bankda navbatda turgan post qolmadi. Yangi postlar qo'shing.",
                )
            except Exception:
                logger.exception("Adminga xabar yuborib bo'lmadi: %s", admin_id)
        return

    db.mark_sent_for_approval(post["id"])
    preview = build_full_text(post["post_text"])
    for admin_id in admin_ids:
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=(
                    f"🆕 Yangi post tasdiq kutmoqda (mavzu: {post['topic_tag']})\n\n"
                    f"{preview}"
                ),
                reply_markup=approval_keyboard(post["id"]),
            )
        except Exception:
            logger.exception("Adminga post yuborib bo'lmadi: %s", admin_id)


async def handle_approval_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    chat_id = update.effective_chat.id

    if not db.is_admin(chat_id):
        await query.answer("Sizda bu amalni bajarish huquqi yo'q.", show_alert=True)
        return

    await query.answer()

    action, post_id_str = query.data.split(":")
    post_id = int(post_id_str)
    post = db.get_post(post_id)

    if not post:
        await query.edit_message_text("Bu post topilmadi (o'chirilgan bo'lishi mumkin).")
        return

    if action == "edit":
        if post["status"] in ("published", "rejected"):
            await query.answer("Bu postni endi tahrirlab bo'lmaydi.", show_alert=True)
            return
        pending_edits[chat_id] = post_id
        await query.edit_message_text(
            f"✏️ Postning yangi matnini yozib yuboring (mavzu: {post['topic_tag']}).\n\n"
            "Eslatma: pastki imzo qatori (\"Sizni tabiiy sog'lom qiluvchi dastur...\") "
            "avtomatik qo'shiladi, uni qayta yozish shart emas."
        )
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


async def handle_edit_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin tahrirlash rejimida bo'lsa, keyingi oddiy xabarini yangi post matni deb qabul qiladi."""
    chat_id = update.effective_chat.id
    if chat_id not in pending_edits:
        return
    if not db.is_admin(chat_id):
        return

    post_id = pending_edits.pop(chat_id)
    new_text = update.message.text
    db.update_post_text(post_id, new_text)

    preview = build_full_text(new_text)
    await update.message.reply_text(
        f"✅ Post yangilandi. Tasdiqlash uchun ko'rib chiqing:\n\n{preview}",
        reply_markup=approval_keyboard(post_id),
    )


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    await update.message.reply_text(
        "Salom! Bu Radnoy Content Bot.\n\n"
        f"Sizning shaxsiy chat ID'ingiz: `{chat_id}`\n\n"
        "Agar siz asosiy admin bo'lsangiz, buni Render'dagi ADMIN_CHAT_ID muhit "
        "o'zgaruvchisiga qo'ying. Qo'shimcha admin sifatida qo'shilish uchun "
        "ushbu ID'ni mavjud adminga yuboring — u /addadmin buyrug'i orqali sizga "
        "dostup beradi.",
        parse_mode=ParseMode.MARKDOWN,
    )


async def cmd_queue(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not db.is_admin(update.effective_chat.id):
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
    if not db.is_admin(update.effective_chat.id):
        return
    await send_draft_for_approval(context)


async def cmd_addadmin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if not db.is_admin(chat_id):
        return
    if not context.args:
        await update.message.reply_text("Foydalanish: /addadmin <chat_id>")
        return
    try:
        new_admin_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Chat ID butun son bo'lishi kerak.")
        return

    db.add_admin(new_admin_id, added_by=chat_id)
    await update.message.reply_text(f"✅ Admin qo'shildi: {new_admin_id}")
    try:
        await context.bot.send_message(
            chat_id=new_admin_id,
            text=(
                "🎉 Sizga Radnoy Content Bot'da admin huquqi berildi. "
                "Endi siz ham postlarni ko'rib, tasdiqlash/tahrirlash imkoniga egasiz."
            ),
        )
    except Exception:
        logger.exception("Yangi adminga xabar yuborib bo'lmadi: %s", new_admin_id)


async def cmd_removeadmin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if not db.is_admin(chat_id):
        return
    if not context.args:
        await update.message.reply_text("Foydalanish: /removeadmin <chat_id>")
        return
    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Chat ID butun son bo'lishi kerak.")
        return

    if str(target_id) == str(config.ADMIN_CHAT_ID):
        await update.message.reply_text("Asosiy adminni o'chirib bo'lmaydi.")
        return

    removed = db.remove_admin(target_id)
    if removed:
        await update.message.reply_text(f"❌ Admin o'chirildi: {target_id}")
    else:
        await update.message.reply_text("Bu ID qo'shimcha adminlar ro'yxatida topilmadi.")


async def cmd_admins(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not db.is_admin(update.effective_chat.id):
        return
    lines = [f"👑 Asosiy admin: {config.ADMIN_CHAT_ID}"]
    extra = db.list_extra_admins()
    if extra:
        lines.append("\nQo'shimcha adminlar:")
        for row in extra:
            lines.append(f"• {row['chat_id']}")
    else:
        lines.append("\nQo'shimcha adminlar yo'q.")
    await update.message.reply_text("\n".join(lines))


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
    threading.Thread(target=start_health_server, daemon=True).start()

    app = Application.builder().token(config.BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("queue", cmd_queue))
    app.add_handler(CommandHandler("postnow", cmd_postnow))
    app.add_handler(CommandHandler("addadmin", cmd_addadmin))
    app.add_handler(CommandHandler("removeadmin", cmd_removeadmin))
    app.add_handler(CommandHandler("admins", cmd_admins))
    app.add_handler(CallbackQueryHandler(handle_approval_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_edit_message))

    for t in parse_post_times():
        app.job_queue.run_daily(send_draft_for_approval, time=t)
        logger.info("Kunlik post vaqti sozlandi: %s", t)

    logger.info("Radnoy Content Bot ishga tushdi.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
