"""CSV export tests: content, column set, filter honoring."""

import csv
import io


def _seed(client):
    client.post("/webhook/telegram", json={"update_id": 1, "message": {
        "message_id": 1, "from": {"id": 1, "first_name": "А"}, "chat": {"id": 1, "type": "private"},
        "date": 1760000000, "text": "Сколько стоит интеграция с 1С? Александр, a.petrov@company.ru"}})
    client.post("/webhook/telegram", json={"update_id": 2, "message": {
        "message_id": 2, "from": {"id": 2, "first_name": "О"}, "chat": {"id": 2, "type": "private"},
        "date": 1760000001, "text": "Ошибка оплаты: деньги списались. Ольга +7 900 123-45-67"}})
    client.post("/webhook/telegram", json={"update_id": 3, "message": {
        "message_id": 3, "from": {"id": 3, "first_name": "S"}, "chat": {"id": 3, "type": "private"},
        "date": 1760000002, "text": "Заработок из дома!!! Пиши скорее"}})


def _parse(response) -> list[dict]:
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]
    return list(csv.DictReader(io.StringIO(response.text, newline=""), delimiter=";"))


def test_export_contains_all_leads(client):
    _seed(client)
    rows = _parse(client.get("/api/leads/export.csv"))
    assert len(rows) == 3
    assert {r["type"] for r in rows} == {"price_question", "support", "spam"}
    by_id = {r["id"]: r for r in rows}
    assert by_id["1"]["contact"] == "a.petrov@company.ru"
    assert by_id["2"]["urgency"] == "high"


def test_export_honors_filters(client):
    _seed(client)
    rows = _parse(client.get("/api/leads/export.csv", params={"type": "support"}))
    assert len(rows) == 1
    assert rows[0]["type"] == "support"


def test_export_empty_registry(client):
    rows = _parse(client.get("/api/leads/export.csv"))
    assert rows == []
