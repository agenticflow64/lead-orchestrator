"""Notifications: real Telegram when configured, local log + dashboard feed otherwise."""

import logging
import os

import httpx

from . import db
from .config import settings

log = logging.getLogger("leadorch.notifier")

URGENCY_MARK = {"high": "🔴 СРОЧНО", "medium": "🟡", "low": "🟢"}
TYPE_LABELS_RU = {
    "price_question": "вопрос о цене",
    "support": "техподдержка",
    "complaint": "жалоба",
    "partnership": "сотрудничество",
    "spam": "спам",
    "other": "другое",
}


def format_lead_message(lead: dict) -> str:
    """Human-readable notification text for a classified lead."""
    lines = [
        f"{URGENCY_MARK.get(lead['urgency'], '')} Новая заявка #{lead['id']} — "
        f"{TYPE_LABELS_RU.get(lead['type'], lead['type'])}".strip(),
        f"Суть: {lead['summary'] or lead['text'][:120]}",
    ]
    if lead["name"]:
        lines.append(f"Имя: {lead['name']}")
    if lead["contact"]:
        lines.append(f"Контакт: {lead['contact']}")
    lines.append(f"Срочность: {lead['urgency']}")
    return "\n".join(lines)


def _send_telegram(text: str) -> None:
    response = httpx.post(
        f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
        json={"chat_id": settings.telegram_chat_id, "text": text},
        timeout=15,
    )
    response.raise_for_status()


def _append_log(text: str) -> None:
    os.makedirs(os.path.dirname(settings.notifications_log), exist_ok=True)
    with open(settings.notifications_log, "a", encoding="utf-8") as fh:
        fh.write(text.replace("\n", " | ") + "\n")


def notify_lead(lead: dict) -> str:
    """Dispatch a notification for a classified lead. Returns the channel used.

    Spam leads are recorded in the registry but never disturb the responsible person.
    """
    if lead["type"] == "spam":
        log.info("spam lead #%s suppressed from notifications", lead["id"])
        return "suppressed"

    text = format_lead_message(lead)
    if settings.telegram_enabled:
        try:
            _send_telegram(text)
            db.insert_notification(channel="telegram", recipient=settings.telegram_chat_id, text=text, lead_id=lead["id"])
            return "telegram"
        except Exception as exc:  # noqa: BLE001 — notification failure must not lose the lead
            log.error("telegram send failed, falling back to log: %s", exc)
    _append_log(text)
    db.insert_notification(channel="log", recipient="notifications.log", text=text, lead_id=lead["id"])
    return "log"
