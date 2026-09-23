"""Supabase-based content bank access for the Radnoy content bot."""

from datetime import datetime, timedelta, timezone
from typing import Optional

from supabase import create_client, Client

import config

_client: Optional[Client] = None


def get_client() -> Client:
    global _client
    if _client is None:
        _client = create_client(config.SUPABASE_URL, config.SUPABASE_KEY)
    return _client


def get_recent_topics(days: int = None) -> set:
    """Topic tags published within the last `days` days."""
    days = days or config.REPEAT_AVOID_DAYS
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    res = (
        get_client()
        .table("content_bank")
        .select("topic_tag")
        .eq("status", "published")
        .gte("published_at", cutoff)
        .execute()
    )
    return {row["topic_tag"] for row in res.data}


def get_next_post_for_approval() -> Optional[dict]:
    """Pick the oldest queued post, preferring a topic not posted recently."""
    res = (
        get_client()
        .table("content_bank")
        .select("*")
        .eq("status", "queued")
        .order("created_at", desc=False)
        .execute()
    )
    queued = res.data
    if not queued:
        return None

    recent_topics = get_recent_topics()
    for post in queued:
        if post["topic_tag"] not in recent_topics:
            return post
    # Every queued topic was covered recently — better to post something
    # than to post nothing, so fall back to the oldest queued item.
    return queued[0]


def get_post(post_id: int) -> Optional[dict]:
    res = get_client().table("content_bank").select("*").eq("id", post_id).execute()
    return res.data[0] if res.data else None


def mark_sent_for_approval(post_id: int) -> None:
    get_client().table("content_bank").update(
        {
            "status": "sent_for_approval",
            "sent_for_approval_at": datetime.now(timezone.utc).isoformat(),
        }
    ).eq("id", post_id).execute()


def mark_published(post_id: int, telegram_message_id: int) -> None:
    get_client().table("content_bank").update(
        {
            "status": "published",
            "published_at": datetime.now(timezone.utc).isoformat(),
            "telegram_message_id": telegram_message_id,
        }
    ).eq("id", post_id).execute()


def mark_rejected(post_id: int, notes: str = "") -> None:
    get_client().table("content_bank").update(
        {"status": "rejected", "notes": notes}
    ).eq("id", post_id).execute()


def counts() -> dict:
    result = {}
    for status in ("queued", "sent_for_approval", "approved", "rejected", "published"):
        res = (
            get_client()
            .table("content_bank")
            .select("id", count="exact")
            .eq("status", status)
            .execute()
        )
        result[status] = res.count or 0
    return result
