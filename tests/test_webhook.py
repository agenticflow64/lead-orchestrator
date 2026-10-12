"""Webhook endpoint tests: Bot API update shape, pipeline side effects, status patching."""


def _update(text: str, chat_id: int = 111, first_name: str = "Ольга") -> dict:
    return {
        "update_id": 1001,
        "message": {
            "message_id": 42,
            "from": {"id": chat_id, "is_bot": False, "first_name": first_name, "language_code": "ru"},
            "chat": {"id": chat_id, "first_name": first_name, "type": "private"},
            "date": 1760000000,
            "text": text,
        },
    }


def test_webhook_creates_classified_lead(client):
    response = client.post(
        "/webhook/telegram",
        json=_update("Ошибка оплаты: деньги списались, но заказ не оформился. Ольга +7 900 123-45-67"),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["type"] == "support"
    assert body["urgency"] == "high"

    leads = client.get("/api/leads").json()
    assert len(leads) == 1
    lead = leads[0]
    assert lead["source"] == "telegram"
    assert lead["name"] == "Ольга"
    assert lead["contact"] == "+7 900 123-45-67"
    assert lead["status"] == "new"
    assert lead["llm_provider"] == "rules"


def test_webhook_notifies_for_real_leads(client):
    client.post("/webhook/telegram", json=_update("Не приходит письмо подтверждения. Иван, ivan@mail.ru"))
    notes = client.get("/api/notifications").json()
    assert len(notes) == 1
    assert notes[0]["channel"] == "log"
    assert "Иван" in notes[0]["text"]


def test_webhook_suppresses_spam_notification(client):
    client.post("/webhook/telegram", json=_update("КУПИЮ ГОТОВЫЙ БИЗНЕС ПИШИ В ЛИС $$$ БЫСТРО ВЫГОДНО"))
    leads = client.get("/api/leads").json()
    assert len(leads) == 1
    assert leads[0]["type"] == "spam"
    assert client.get("/api/notifications").json() == []


def test_webhook_skips_updates_without_text(client):
    update = {"update_id": 1002, "edited_message": {"message_id": 5, "chat": {"id": 1}, "edit_date": 1760000000}}
    response = client.post("/webhook/telegram", json=update)
    assert response.status_code == 200
    assert response.json()["skipped"]
    assert client.get("/api/leads").json() == []


def test_webhook_rejects_non_object(client):
    response = client.post("/webhook/telegram", json=[1, 2, 3])
    assert response.status_code == 400


def test_web_form_channel(client):
    response = client.post(
        "/api/leads",
        json={"name": "Роман", "contact": "roman@agency.dev", "text": "Хотим предложить сотрудничество по проектам"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["type"] == "partnership"
    lead = client.get("/api/leads").json()[0]
    assert lead["source"] == "web_form"
    assert lead["contact"] == "roman@agency.dev"


def test_status_patch_and_404(client):
    client.post("/webhook/telegram", json=_update("Сколько стоит доработка кабинета? Марина"))
    lead_id = client.get("/api/leads").json()[0]["id"]

    ok = client.patch(f"/api/leads/{lead_id}", json={"status": "in_progress"})
    assert ok.status_code == 200
    assert client.get("/api/leads").json()[0]["status"] == "in_progress"

    missing = client.patch("/api/leads/9999", json={"status": "done"})
    assert missing.status_code == 404

    bad = client.patch(f"/api/leads/{lead_id}", json={"status": "archived"})
    assert bad.status_code == 422


def test_filters(client):
    client.post("/webhook/telegram", json=_update("Сколько стоит интеграция? Александр, a@b.ru"))
    client.post("/webhook/telegram", json=_update("Ошибка оплаты, деньги списались! Ольга +7 900 123-45-67"))
    client.post("/webhook/telegram", json=_update("КУПИЮ БИЗНЕС $$$"))

    assert len(client.get("/api/leads").json()) == 3
    only_support = client.get("/api/leads", params={"type": "support"}).json()
    assert [l["type"] for l in only_support] == ["support"]
    high = client.get("/api/leads", params={"urgency": "high"}).json()
    assert all(l["urgency"] == "high" for l in high)
    assert len(high) == 1
