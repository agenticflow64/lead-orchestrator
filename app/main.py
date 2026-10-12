"""FastAPI service: webhook + web form inbound, storage, export, notifications."""

import csv
import io
import logging
import time
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from . import db, notifier, telegram
from .classifier import classify

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("leadorch.main")

app = FastAPI(title="Lead Orchestrator", version="1.0.0")

@app.on_event("startup")
def _startup() -> None:
    db.init_db()
    log.info("storage ready; telegram notifications: %s", "real" if notifier.settings.telegram_enabled else "mock(log)")


# ---------------------------------------------------------------------------
# Shared pipeline: text -> classification -> registry row -> notification
# ---------------------------------------------------------------------------


def process_lead(*, source: str, text: str) -> dict[str, Any]:
    """Full agent pipeline for one lead. Returns the stored row."""
    t0 = time.monotonic()
    result = classify(text)
    processing_ms = int((time.monotonic() - t0) * 1000)
    lead_id = db.insert_lead(
        source=source,
        text=text,
        type_=result["type"],
        urgency=result["urgency"],
        name=result["name"],
        contact=result["contact"],
        summary=result["summary"],
        llm_provider=result.get("provider", ""),
        processing_ms=processing_ms,
    )
    lead = db.get_lead(lead_id)
    channel = notifier.notify_lead(lead)
    log.info(
        "lead #%s from %s: type=%s urgency=%s provider=%s notify=%s (%d ms)",
        lead_id, source, result["type"], result["urgency"], result.get("provider"), channel, processing_ms,
    )
    return lead


# ---------------------------------------------------------------------------
# Inbound channels
# ---------------------------------------------------------------------------


@app.post("/webhook/telegram")
async def telegram_webhook(request: Request) -> JSONResponse:
    """Telegram Bot API webhook: message text becomes a lead."""
    update = await request.json()
    if not isinstance(update, dict):
        raise HTTPException(status_code=400, detail="invalid update")
    message = telegram.extract_message(update)
    if message is None:
        return JSONResponse({"ok": True, "skipped": "no text message"})
    lead = process_lead(source="telegram", text=message["text"])
    if lead["type"] != "spam":
        telegram.send_reply(
            message["chat_id"],
            "Заявка принята и зарегистрирована под номером "
            f"#{lead['id']}. Мы свяжемся с вами в рабочее время.",
        )
    return JSONResponse({"ok": True, "lead_id": lead["id"], "type": lead["type"], "urgency": lead["urgency"]})


class LeadForm(BaseModel):
    name: str = Field(default="", max_length=200)
    contact: str = Field(default="", max_length=200)
    text: str = Field(min_length=1, max_length=4000)


@app.post("/api/leads")
async def create_lead_web(form: LeadForm) -> JSONResponse:
    """Second inbound channel: the web form on the dashboard."""
    signature = _signature(form)
    text = f"{form.text}\n{signature}" if signature else form.text
    lead = process_lead(source="web_form", text=text)
    return JSONResponse({"ok": True, "lead_id": lead["id"], "type": lead["type"], "urgency": lead["urgency"]})


def _signature(form: LeadForm) -> str:
    parts = [p for p in (form.name.strip(), form.contact.strip()) if p]
    return ", ".join(parts)


# ---------------------------------------------------------------------------
# Registry API + export
# ---------------------------------------------------------------------------


@app.get("/api/leads")
def get_leads(
    type: str | None = Query(default=None),
    urgency: str | None = Query(default=None),
    status: str | None = Query(default=None),
    order: str = Query(default="desc", pattern="^(asc|desc)$"),
) -> list[dict[str, Any]]:
    return db.list_leads(type_=type, urgency=urgency, status=status, order=order)


class StatusUpdate(BaseModel):
    status: str = Field(pattern="^(new|in_progress|done)$")


@app.patch("/api/leads/{lead_id}")
def patch_lead(lead_id: int, payload: StatusUpdate) -> dict[str, Any]:
    if not db.update_lead_status(lead_id, payload.status):
        raise HTTPException(status_code=404, detail="lead not found")
    return {"ok": True, "id": lead_id, "status": payload.status}


@app.get("/api/leads/export.csv")
def export_csv(
    type: str | None = Query(default=None),
    urgency: str | None = Query(default=None),
    status: str | None = Query(default=None),
) -> StreamingResponse:
    """CSV export honoring the same filters as the table."""
    leads = db.list_leads(type_=type, urgency=urgency, status=status, order="desc", limit=100000)
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow(["id", "created_at", "source", "type", "urgency", "status", "name", "contact", "summary", "text"])
    for lead in leads:
        writer.writerow([lead[k] for k in ("id", "created_at", "source", "type", "urgency", "status", "name", "contact", "summary", "text")])
    buffer.seek(0)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=leads.csv"},
    )


@app.get("/api/notifications")
def get_notifications(limit: int = Query(default=20, le=100)) -> list[dict[str, Any]]:
    return db.list_notifications(limit=limit)


@app.get("/api/stats")
def get_stats() -> dict[str, Any]:
    return db.stats()


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"ok": True}


@app.get("/api/meta")
def meta() -> dict[str, Any]:
    """Runtime mode info for the dashboard header (no secrets, names only)."""
    from .config import settings

    return {
        "telegram_enabled": settings.telegram_enabled,
        "openrouter_enabled": settings.openrouter_enabled,
        "glm_enabled": settings.glm_enabled,
        "model": settings.openrouter_model if settings.openrouter_enabled else "",
    }


@app.get("/")
def index() -> FileResponse:
    return FileResponse("app/static/index.html", media_type="text/html")
