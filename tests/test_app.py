import csv

import pytest

import notify
from app import create_app

GOOD = {"name": "Priya Sharma", "email": "priya@example.com", "phone": "+91 00000 43210",
        "service": "Modular kitchen", "message": "2BHK in Pune, budget around 4L"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("LEADS_CSV", str(tmp_path / "leads.csv"))
    monkeypatch.delenv("GOOGLE_SHEET_ID", raising=False)
    monkeypatch.delenv("WEBHOOK_SECRET", raising=False)
    for _, keys in notify.CHANNELS.values():
        for k in keys:
            monkeypatch.delenv(k, raising=False)
    return create_app().test_client()


def read_leads(tmp_path):
    path = tmp_path / "leads.csv"
    if not path.exists():
        return []
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def test_form_page_loads(client):
    assert b"Send enquiry" in client.get("/").data


def test_valid_submission_is_saved(client, tmp_path):
    res = client.post("/submit", data=GOOD)
    assert res.status_code == 200
    assert res.json["ok"]

    rows = read_leads(tmp_path)
    assert len(rows) == 1
    assert rows[0]["email"] == "priya@example.com"
    assert rows[0]["source"] == "website form"


def test_invalid_submission_returns_errors(client, tmp_path):
    res = client.post("/submit", data={**GOOD, "email": "not-an-email", "name": ""})
    assert res.status_code == 400
    assert set(res.json["errors"]) == {"email", "name"}
    assert read_leads(tmp_path) == []


def test_honeypot_is_dropped_quietly(client, tmp_path):
    res = client.post("/submit", data={**GOOD, "website": "http://spam.example"})
    assert res.status_code == 200
    assert read_leads(tmp_path) == []


def test_webhook_maps_other_field_names(client, tmp_path):
    res = client.post("/webhook?source=landing-page", json={
        "Full Name": "Rahul", "Email Address": "rahul@example.com", "Mobile": "0000043210",
        "Comments": "Call me after 6pm",
    })
    assert res.status_code == 200
    row = read_leads(tmp_path)[0]
    assert row["name"] == "Rahul"
    assert row["phone"] == "0000043210"
    assert row["message"] == "Call me after 6pm"
    assert row["source"] == "landing-page"


def test_webhook_tally_format(client, tmp_path):
    payload = {"eventType": "FORM_RESPONSE", "data": {"fields": [
        {"label": "Name", "value": "Anita"},
        {"label": "Email", "value": "anita@example.com"},
    ]}}
    assert client.post("/webhook", json=payload).status_code == 200
    assert read_leads(tmp_path)[0]["name"] == "Anita"


def test_webhook_secret(client, monkeypatch):
    monkeypatch.setenv("WEBHOOK_SECRET", "s3cret")
    assert client.post("/webhook", json=GOOD).status_code == 401
    assert client.post("/webhook?key=s3cret", json=GOOD).status_code == 200


def test_failed_notification_still_saves(client, tmp_path, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "x")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "1")

    def boom(lead):
        raise ConnectionError("telegram down")

    monkeypatch.setitem(notify.CHANNELS, "telegram", (boom, ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"]))

    assert client.post("/submit", data=GOOD).status_code == 200
    assert len(read_leads(tmp_path)) == 1


def test_formula_text_is_neutralized(client, tmp_path):
    res = client.post("/submit", data={**GOOD, "name": '=HYPERLINK("http://evil.example","x")',
                                       "message": "-2+3+cmd|' /C calc'!A0"})
    assert res.status_code == 200
    row = read_leads(tmp_path)[0]
    assert row["name"].startswith("'=")
    assert row["message"].startswith("'-")
    assert row["phone"] == "+91 00000 43210"


def test_lead_message_format():
    text = notify.format_lead({**GOOD, "source": "website form", "received_at": "2026-10-27 09:00:00 UTC"})
    assert text.startswith("New enquiry from Priya Sharma")
    assert "+91 00000 43210" in text
