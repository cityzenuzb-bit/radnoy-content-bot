# Radnoy Content Bot

@radnoy_trener Telegram kanaliga kuniga 2 marta sog'lom turmush tarzi
haqida post joylashni yarim-avtomatik qiladigan bot. Har bir post
kanalga chiqishdan oldin adminga (DM orqali) ko'rsatiladi va faqat
✅ tugmasi bosilgandan keyin joylanadi.

## Ishlash tartibi

1. Belgilangan vaqtda (default 10:00 va 18:00, Asia/Tashkent) bot
   Supabase'dagi `content_bank` jadvalidan navbatdagi (`status='queued'`)
   postni oladi — so'nggi 60 kunda yozilmagan mavzuga ustunlik beradi.
2. Postni to'liq matn holida (majburiy imzo bilan) adminga DM qiladi,
   ✅/❌ tugmalari bilan.
3. Admin ✅ bossa — bot postni @radnoy_trener kanaliga joylaydi.
   ❌ bossa — post rad etilgan deb belgilanadi va boshqa taklif qilinmaydi.

## Kerakli muhit o'zgaruvchilari (Render → Environment)

| Nomi | Tavsif |
|---|---|
| `BOT_TOKEN` | BotFather'dan olingan token |
| `SUPABASE_URL` | `https://jgyuylnxyotpavzhlqno.supabase.co` |
| `SUPABASE_KEY` | Supabase anon/publishable kalit |
| `CHANNEL_ID` | `@radnoy_trener` |
| `ADMIN_CHAT_ID` | Adminning shaxsiy Telegram chat ID'si (pastga qarang) |
| `POST_TIMES` | (ixtiyoriy) masalan `10:00,18:00` |
| `FOOTER_TEXT` | (ixtiyoriy) default: `Sizni tabiiy sog'lom qiluvchi dastur - @rtrenerbot` |
| `REPEAT_AVOID_DAYS` | (ixtiyoriy) default `60` |

### ADMIN_CHAT_ID qanday olinadi

1. Botni Telegram'da toping va `/start` yozing.
2. Bot sizga shaxsiy chat ID raqamingizni yuboradi.
3. Shu raqamni Render'dagi `ADMIN_CHAT_ID` muhit o'zgaruvchisiga qo'ying
   va xizmatni qayta ishga tushiring (redeploy).

## Yangi post qo'shish

Hozircha kontent qo'lda (Claude bilan birga) tayyorlanadi va
`content_bank` jadvaliga qo'shiladi. `add_posts.py` faylidagi `POSTS`
ro'yxatini to'ldirib, uni Supabase SQL Editor orqali yoki lokal skript
sifatida ishga tushirish mumkin.

## Buyruqlar

- `/start` — chat ID'ni ko'rsatadi
- `/queue` — navbatdagi/joylangan postlar sonini ko'rsatadi (faqat admin)
- `/postnow` — navbatdagi postni darhol tasdiqlashga yuboradi, jadvalni
  kutmasdan (test uchun, faqat admin)
