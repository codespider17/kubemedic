import json
from pathlib import Path

FIXTURE = Path(__file__).parent / "fixtures" / "alertmanager-firing.json"


def test_healthz(client) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readyz(client) -> None:
    response = client.get("/readyz")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_alertmanager_webhook_accepts_fixture(client) -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    response = client.post("/api/v1/alerts/webhook", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] == 1
    assert body["alerts"][0]["alertname"] == "DemoPodRestarting"
    assert body["alerts"][0]["namespace"] == "demo"
    assert body["incident_ids"][0].startswith("inc-")


def test_alertmanager_webhook_rejects_invalid_json(client) -> None:
    response = client.post(
        "/api/v1/alerts/webhook",
        content="{invalid-json",
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422
