import logging
import os
import smtplib
from email.message import EmailMessage

import requests

log = logging.getLogger("leads")


def format_lead(lead):
    lines = [
        f"New enquiry from {lead['name']}",
        "",
        f"Email:   {lead['email']}",
        f"Phone:   {lead['phone'] or '-'}",
        f"Service: {lead['service'] or '-'}",
        f"Source:  {lead['source']}",
        f"Time:    {lead['received_at']}",
    ]
    if lead["message"]:
        lines += ["", lead["message"]]
    return "\n".join(lines)


def send_email(lead):
    msg = EmailMessage()
    msg["Subject"] = f"New lead: {lead['name']}" + (f" ({lead['service']})" if lead["service"] else "")
    msg["From"] = os.getenv("SMTP_FROM") or os.environ["SMTP_USER"]
    msg["To"] = os.environ["NOTIFY_EMAIL"]
    msg["Reply-To"] = lead["email"]
    msg.set_content(format_lead(lead))

    with smtplib.SMTP(os.getenv("SMTP_HOST", "smtp.gmail.com"), int(os.getenv("SMTP_PORT", 587)), timeout=15) as s:
        s.starttls()
        s.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
        s.send_message(msg)


def send_telegram(lead):
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    r = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": os.environ["TELEGRAM_CHAT_ID"], "text": format_lead(lead)},
        timeout=10,
    )
    r.raise_for_status()


def send_whatsapp(lead):
    sid = os.environ["TWILIO_ACCOUNT_SID"]
    r = requests.post(
        f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
        auth=(sid, os.environ["TWILIO_AUTH_TOKEN"]),
        data={
            "From": "whatsapp:" + os.environ["TWILIO_WHATSAPP_FROM"],
            "To": "whatsapp:" + os.environ["WHATSAPP_TO"],
            "Body": format_lead(lead),
        },
        timeout=10,
    )
    r.raise_for_status()


CHANNELS = {
    "email": (send_email, ["SMTP_USER", "SMTP_PASSWORD", "NOTIFY_EMAIL"]),
    "telegram": (send_telegram, ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"]),
    "whatsapp": (send_whatsapp, ["TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_WHATSAPP_FROM", "WHATSAPP_TO"]),
}


def enabled():
    return [name for name, (_, keys) in CHANNELS.items() if all(os.getenv(k) for k in keys)]


def send_all(lead):
    sent = []
    for name in enabled():
        func = CHANNELS[name][0]
        try:
            func(lead)
            sent.append(name)
        except Exception as e:
            # a failed alert shouldn't lose the lead, it's already saved
            log.error("%s notification failed: %s", name, e)
    return sent
