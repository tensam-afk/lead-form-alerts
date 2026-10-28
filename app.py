import hmac
import logging
import os
import re
from datetime import datetime, timezone

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request

import notify
import storage

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("leads")

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# webhook payloads from form builders use different names for the same thing
FIELD_ALIASES = {
    "name": ["name", "full_name", "fullname", "your_name"],
    "email": ["email", "email_address", "your_email"],
    "phone": ["phone", "phone_number", "mobile", "whatsapp"],
    "message": ["message", "comments", "details", "enquiry", "inquiry"],
    "service": ["service", "interested_in", "topic"],
}


def normalize(data):
    lower = {str(k).strip().lower().replace(" ", "_"): v for k, v in data.items()}
    lead = {}
    for field, keys in FIELD_ALIASES.items():
        value = next((lower[k] for k in keys if lower.get(k)), "")
        lead[field] = str(value).strip()
    return lead


def validate(lead):
    errors = {}
    if len(lead["name"]) < 2:
        errors["name"] = "Please enter your name."
    if not EMAIL_RE.match(lead["email"]):
        errors["email"] = "Please enter a valid email address."
    if lead["phone"] and len(re.sub(r"\D", "", lead["phone"])) < 7:
        errors["phone"] = "That phone number looks too short."
    if len(lead["message"]) > 5000:
        errors["message"] = "Message is too long."
    return errors


def handle_lead(raw, source):
    # bots fill every field, people never see this one
    if raw.get("website"):
        log.info("dropped honeypot submission from %s", request.remote_addr)
        return {"ok": True}, 200

    lead = normalize(raw)
    errors = validate(lead)
    if errors:
        return {"ok": False, "errors": errors}, 400

    lead["source"] = source
    lead["received_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    storage.save_lead(lead)
    sent = notify.send_all(lead)
    log.info("new lead from %s <%s>, notified via %s", lead["name"], lead["email"], sent or "nothing")
    return {"ok": True}, 200


def create_app():
    app = Flask(__name__)

    @app.get("/")
    def form():
        return render_template("form.html", business=os.getenv("BUSINESS_NAME", "Acme Interiors"))

    @app.post("/submit")
    def submit():
        body, status = handle_lead(request.form.to_dict(), "website form")
        return jsonify(body), status

    @app.post("/webhook")
    def webhook():
        secret = os.getenv("WEBHOOK_SECRET")
        given = request.args.get("key") or request.headers.get("X-Webhook-Key") or ""
        if secret and not hmac.compare_digest(given.encode(), secret.encode()):
            return jsonify({"ok": False, "error": "unauthorized"}), 401

        data = request.get_json(silent=True)
        if data is None:
            data = request.form.to_dict()
        # Tally and similar tools nest answers as a list of {label, value}
        if isinstance(data.get("data"), dict) and "fields" in data["data"]:
            data = {f.get("label", ""): f.get("value", "") for f in data["data"]["fields"]}

        body, status = handle_lead(data, request.args.get("source", "webhook"))
        return jsonify(body), status

    @app.get("/health")
    def health():
        return {"ok": True, "storage": storage.backend_name(), "notifiers": notify.enabled()}

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=os.getenv("FLASK_DEBUG") == "1", port=int(os.getenv("PORT", 5000)))
