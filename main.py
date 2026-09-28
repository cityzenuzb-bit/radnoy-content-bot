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

# chat_id -> yangi post/rubrika kiritishni kutayotgan adminlar (xotirada saqlanadi)
pending_new_posts: set[int] = set()


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
    """Tasdiq kutayotgan post bor bo'lsa o'shani qayta yuboradi (mavzu
    almashib ketmasligi uchun), aks holda navbatdagi keyingi postni oladi."""
    admin_ids = db.get_all_admin_chat_ids()
    if not admin_ids:
        logger.warning("Hech qanday admin sozlanmagan, post yuborilmadi.")
        return

    post = db.get_pending_approval_post()
    is_resend = post is not None
    if not post:
        removed = db.remove_duplicate_posts()
        if removed:
            logger.info("Bazadan %s ta bir xil (dublikat) post o'chirildi.", removed)
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

    if not is_resend:
        db.mark_sent_for_approval(post["id"])

    preview = build_full_text(post["post_text"])
    header = (
        f"🔁 Hali tasdiqlanmagan post (mavzu: {post['topic_tag']})\n\n"
        if is_resend
        else f"🆕 Yangi post tasdiq kutmoqda (mavzu: {post['topic_tag']})\n\n"
    )
    for admin_id in admin_ids:
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=f"{header}{preview}",
                reply_markup=approval_keyboard(post["id"]),
            )
        except Exception:
            logger.exception("Adminga post yuborib bo'lmadi: %s", admin_id)


def rubrikalar_keyboard(rubrikas: list) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                f"📁 {r['topic_tag']} ({r['count']})", callback_data=f"rubrika:{r['topic_tag']}"
            )
        ]
        for r in rubrikas
    ]
    return InlineKeyboardMarkup(rows)


async def handle_approval_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    chat_id = update.effective_chat.id

    if not db.is_admin(chat_id):
        await query.answer("Sizda bu amalni bajarish huquqi yo'q.", show_alert=True)
        return

    if query.data.startswith("rubrika:"):
        await query.answer()
        topic_tag = query.data.split(":", 1)[1]
        posts = db.list_queued_by_rubrika(topic_tag)
        if not posts:
            await query.edit_message_text(f"📁 «{topic_tag}» rubrikasida hozircha post yo'q.")
            return
        lines = [f"📁 «{topic_tag}» rubrikasidagi navbatdagi postlar:\n"]
        for p in posts:
            preview = p["post_text"].strip().splitlines()[0][:60]
            lines.append(f"#{p['id']} — {preview}")
        back_keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("⬅️ Rubrikalarga qaytish", callback_data="rubrikalar_back")]]
        )
        await query.edit_message_text("\n".join(lines), reply_markup=back_keyboard)
        return

    if query.data == "rubrikalar_back":
        await query.answer()
        rubrikas = db.list_rubrikas()
        if not rubrikas:
            await query.edit_message_text("📁 Hozircha navbatda hech qanday rubrika yo'q.")
            return
        await query.edit_message_text(
            "📁 Rubrikalar (navbatdagi postlar bo'yicha):",
            reply_markup=rubrikalar_keyboard(rubrikas),
        )
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
        pending_new_posts.discard(chat_id)
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
        # Ikkita admin bir vaqtda tasdiqlasa ham kanalga faqat bitta marta
        # joylanishini kafolatlash uchun avval postni "band qilamiz" —
        # faqat shu chaqiruv statusni sent_for_approval'dan published'ga
        # o'zgartira olgan bo'lsagina kanalga yuboramiz.
        claimed = db.try_claim_for_publishing(post_id)
        if not claimed:
            fresh = db.get_post(post_id) or post
            if fresh["status"] == "published":
                await query.edit_message_text(
                    "ℹ️ Bu postni boshqa admin sizdan oldinroq tasdiqlab, "
                    f"kanalga allaqachon joylagan:\n\n{build_full_text(fresh['post_text'])}"
                )
            else:
                await query.edit_message_text(
                    "ℹ️ Bu post boshqa admin tomonidan allaqachon ko'rib chiqilgan."
                )
            return

        full_text = build_full_text(post["post_text"])
        sent = await context.bot.send_message(chat_id=config.CHANNEL_ID, text=full_text)
        db.set_published_message_id(post_id, sent.message_id)
        await query.edit_message_text(f"✅ Kanalga joylandi:\n\n{full_text}")
    elif action == "reject":
        claimed = db.try_claim_for_rejecting(post_id, notes="Admin tomonidan rad etildi")
        if not claimed:
            await query.edit_message_text(
                "ℹ️ Bu post boshqa admin tomonidan allaqachon ko'rib chiqilgan."
            )
            return
        await query.edit_message_text(f"❌ Rad etildi:\n\n{build_full_text(post['post_text'])}")


async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin qandaydir kutilayotgan holatda bo'lsa (post tahrirlash yoki yangi
    post qo'shish), keyingi oddiy xabarini o'sha holatga mos ravishda qabul
    qiladi."""
    chat_id = update.effective_chat.id
    if not db.is_admin(chat_id):
        return

    if chat_id in pending_new_posts:
        pending_new_posts.discard(chat_id)
        raw = update.message.text.strip()
        lines = raw.splitlines()
        if len(lines) < 2 or not lines[0].strip() or not "\n".join(lines[1:]).strip():
            await update.message.reply_text(
                "⚠️ Format noto'g'ri edi, post qo'shilmadi. Birinchi qatorga "
                "rubrika nomini, keyingi qatorlarga post matnini yozib, /yangipost "
                "buyrug'ini qaytadan bering."
            )
            return
        topic_tag = lines[0].strip()
        post_text = "\n".join(lines[1:]).strip()
        new_post = db.add_post(topic_tag, post_text)
        if not new_post:
            await update.message.reply_text("❌ Postni bazaga qo'shib bo'lmadi, qaytadan urinib ko'ring.")
            return
        preview = build_full_text(post_text)
        await update.message.reply_text(
            f"✅ Yangi post navbatga qo'shildi (rubrika: {topic_tag}, #{new_post['id']}):\n\n{preview}"
        )
        return

    if chat_id in pending_edits:
        post_id = pending_edits.pop(chat_id)
        new_text = update.message.text
        db.update_post_text(post_id, new_text)

        preview = build_full_text(new_text)
        await update.message.reply_text(
            f"✅ Post yangilandi. Tasdiqlash uchun ko'rib chiqing:\n\n{preview}",
            reply_markup=approval_keyboard(post_id),
        )
        return


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


async def cmd_mavzular(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Navbatdagi (hali yuborilmagan) postlar ro'yxatini ko'rsatadi — joriy
    tasdiq kutayotgan postga tegmaydi."""
    if not db.is_admin(update.effective_chat.id):
        return
    topics = db.list_queued_topics()
    if not topics:
        await update.message.reply_text("📋 Navbatda boshqa post yo'q.")
        return
    lines = ["📋 Navbatdagi mavzular (tasdiqqa yuborilmagan):"]
    for t in topics:
        lines.append(f"#{t['id']} — {t['topic_tag']}")
    await update.message.reply_text("\n".join(lines))


async def cmd_yangipost(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin yangi content g'oyasini/postini qo'lda navbatga qo'shishni boshlaydi."""
    chat_id = update.effective_chat.id
    if not db.is_admin(chat_id):
        return
    pending_edits.pop(chat_id, None)
    pending_new_posts.add(chat_id)
    await update.message.reply_text(
        "✍️ Yangi post qo'shamiz. Endi bitta xabar sifatida yuboring:\n\n"
        "1-qator: rubrika nomi (masalan: motivatsiya)\n"
        "2-qatordan boshlab: post matni\n\n"
        "Eslatma: pastki imzo qatori avtomatik qo'shiladi, uni yozish shart emas."
    )


async def cmd_rubrikalar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Navbatdagi postlarni rubrika (mavzu guruhi) bo'yicha ko'rsatadi."""
    if not db.is_admin(update.effective_chat.id):
        return
    rubrikas = db.list_rubrikas()
    if not rubrikas:
        await update.message.reply_text("📁 Hozircha navbatda hech qanday rubrika yo'q.")
        return
    await update.message.reply_text(
        "📁 Rubrikalar (navbatdagi postlar bo'yicha):",
        reply_markup=rubrikalar_keyboard(rubrikas),
    )


async def cmd_addadmin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if str(chat_id) != str(config.ADMIN_CHAT_ID):
        await update.message.reply_text(
            "Faqat asosiy admin (creator) yangi admin qo'sha oladi."
        )
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
    if str(chat_id) != str(config.ADMIN_CHAT_ID):
        await update.message.reply_text(
            "Faqat asosiy admin (creator) boshqa adminlarni o'chira oladi."
        )
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
        await update.message.reply_text("Asosiy adminni (creator) o'chirib bo'lmaydi.")
        return

    removed = db.remove_admin(target_id)
    if removed:
        await update.message.reply_text(f"❌ Admin o'chirildi: {target_id}")
    else:
        await update.message.reply_text("Bu ID qo'shimcha adminlar ro'yxatida topilmadi.")


async def cmd_admins(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not db.is_admin(update.effective_chat.id):
        return
    lines = [
        f"👑 Asosiy admin: `{config.ADMIN_CHAT_ID}` — "
        f"[Chat ochish](tg://user?id={config.ADMIN_CHAT_ID})"
    ]
    extra = db.list_extra_admins()
    if extra:
        lines.append("\nQo'shimcha adminlar:")
        for row in extra:
            cid = row["chat_id"]
            lines.append(f"• `{cid}` — [Chat ochish](tg://user?id={cid})")
    else:
        lines.append("\nQo'shimcha adminlar yo'q.")
    lines.append(
        "\n⚠️ Eslatma: \"Chat ochish\" linki Telegramning maxfiylik "
        "sozlamalariga bog'liq — ba'zi foydalanuvchilarda to'g'ridan-to'g'ri "
        "ochilmasligi mumkin."
    )
    await update.message.reply_text(
        "\n".join(lines),
        parse_mode=ParseMode.MARKDOWN,
        disable_web_page_preview=True,
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not db.is_admin(update.effective_chat.id):
        return
    is_creator = str(update.effective_chat.id) == str(config.ADMIN_CHAT_ID)
    lines = [
        "🤖 Radnoy Content Bot — buyruqlar ro'yxati:\n",
        "/start — botni ishga tushirish, chat ID'ingizni ko'rsatadi.",
        "/queue — kontent-bank statistikasi (navbatda, tasdiq kutmoqda, "
        "rad etilgan, joylangan postlar soni).",
        "/postnow — hozir tasdiq kutayotgan post bo'lsa o'shani qayta ko'rsatadi, "
        "bo'lmasa navbatdagi keyingi postni yuboradi.",
        "/mavzular — navbatda turgan (hali yuborilmagan) barcha postlarning "
        "mavzularini ro'yxat qilib ko'rsatadi, joriy tasdiq jarayoniga tegmaydi.",
        "/rubrikalar — navbatdagi postlarni rubrika (mavzu guruhi) bo'yicha "
        "ko'rsatadi, tugmani bosib o'sha rubrikadagi postlar ro'yxatini ochish mumkin.",
        "/yangipost — yangi content g'oyasi/postini qo'lda navbatga qo'shish "
        "(rubrika nomi va matnni so'raydi).",
        "/admins — hozirgi barcha adminlar ro'yxatini ko'rsatadi.",
        "/help — shu buyruqlar ro'yxatini qayta ko'rsatadi.",
        "\nHar bir post ostidagi tugmalar:",
        "✅ Tasdiqlash — postni kanalga joylaydi.",
        "❌ Rad etish — postni bekor qiladi (kanalga joylanmaydi).",
        "✏️ Tahrirlash — postning matnini yozib tuzatish imkonini beradi.",
    ]
    if is_creator:
        lines.append(
            "\n👑 Faqat sizga (asosiy admin/creator) tegishli buyruqlar:"
        )
        lines.append("/addadmin <chat_id> — yangi adminga dostup beradi.")
        lines.append("/removeadmin <chat_id> — adminni dostupdan mahrum qiladi.")
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
    app.add_handler(CommandHandler("mavzular", cmd_mavzular))
    app.add_handler(CommandHandler("rubrikalar", cmd_rubrikalar))
    app.add_handler(CommandHandler("yangipost", cmd_yangipost))
    app.add_handler(CommandHandler("addadmin", cmd_addadmin))
    app.add_handler(CommandHandler("removeadmin", cmd_removeadmin))
    app.add_handler(CommandHandler("admins", cmd_admins))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CallbackQueryHandler(handle_approval_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))

    for t in parse_post_times():
        app.job_queue.run_daily(send_draft_for_approval, time=t)
        logger.info("Kunlik post vaqti sozlandi: %s", t)

    logger.info("Radnoy Content Bot ishga tushdi.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
