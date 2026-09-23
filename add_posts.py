"""
Kontent-bankka yangi postlar qo'shish uchun yordamchi skript.

Ishlatish: POSTS ro'yxatini to'ldirib, `python add_posts.py` ni lokal
(yoki Render Shell) orqali ishga tushiring. Har bir yozuv:
    {"topic_tag": "kaloriya", "post_text": "..."}

post_text'ga footer qatorini QO'SHMANG — botning o'zi avtomatik qo'shadi.
"""

import os
from supabase import create_client

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]

POSTS = [
    # Bu yerga yangi postlar qo'shiladi (topic_tag, post_text juftligi).
]


def main():
    if not POSTS:
        print("POSTS ro'yxati bo'sh — qo'shiladigan post yo'q.")
        return
    client = create_client(SUPABASE_URL, SUPABASE_KEY)
    rows = [{"topic_tag": p["topic_tag"], "post_text": p["post_text"]} for p in POSTS]
    res = client.table("content_bank").insert(rows).execute()
    print(f"{len(res.data)} ta post kontent-bankka qo'shildi.")


if __name__ == "__main__":
    main()
