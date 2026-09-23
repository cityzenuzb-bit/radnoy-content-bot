import os

BOT_TOKEN = os.environ["BOT_TOKEN"]

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]

CHANNEL_ID = os.environ.get("CHANNEL_ID", "@radnoy_trener")

# Admin's personal Telegram chat id (a number), where the bot sends drafts
# for approval. Left empty until the admin runs /start on the bot and
# copies the id it replies with into the ADMIN_CHAT_ID env var on Render.
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID", "")

# Comma-separated HH:MM (24h) times, in Asia/Tashkent time, when the bot
# sends a new draft to the admin for approval. Default: two posts a day.
POST_TIMES = os.environ.get("POST_TIMES", "10:00,18:00")

TIMEZONE = "Asia/Tashkent"

# Mandatory footer line appended to every published post.
FOOTER_TEXT = os.environ.get(
    "FOOTER_TEXT", "Sizni tabiiy sog'lom qiluvchi dastur - @rtrenerbot"
)

# How many days back to look when avoiding repeating the same topic.
REPEAT_AVOID_DAYS = int(os.environ.get("REPEAT_AVOID_DAYS", "60"))
