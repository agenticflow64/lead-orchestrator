"""Inbound Telegram update parsing (Bot API webhook format) and outbound replies."""

import logging

import httpx

from .config import settings

log = logging.getLogger("leadorch.telegram")


def extract_message(update: dict) -> dict | None:
    """Pull {'chat_id', 'message_id', 'text', 'sender_name'} out of a Bot API update.

    Returns None for updates without user text (edits, callbacks, channel posts...).
    """
    message = update.get("message") or update.get("channel_post")
    if not message or not message.get("text"):
        return None
    chat = message.get("chat", {})
    sender = ""
    if "from" in message:
        sender = " ".join(x for x in (message["from"].get("first_name"), message["from"].get("last_name")) if x)
    elif "title" in chat:
        sender = chat["title"]
    return {
        "chat_id": str(chat.get("id", "")),
        "message_id": message.get("message_id"),
        "text": message["text"],
        "sender_name": sender,
    }


def send_reply(chat_id: str, text: str) -> bool:
    """Confirmation to the client in the bot chat; no-op in mock mode."""
    if not settings.telegram_bot_token:
        log.info("mock telegram reply to %s: %s", chat_id, text)
        return False
    try:
        response = httpx.post(
            f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=15,
        )
        response.raise_for_status()
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("telegram reply failed: %s", exc)
        return False
