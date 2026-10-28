import csv
import os
import re
import threading
from pathlib import Path

COLUMNS = ["received_at", "name", "email", "phone", "service", "message", "source"]

_lock = threading.Lock()
_sheet = None


def backend_name():
    return "google_sheets" if os.getenv("GOOGLE_SHEET_ID") else "csv"


def _worksheet():
    global _sheet
    if _sheet is None:
        import gspread  # only needed when Sheets is configured

        gc = gspread.service_account(filename=os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json"))
        ws = gc.open_by_key(os.environ["GOOGLE_SHEET_ID"]).sheet1
        if not ws.row_values(1):
            ws.append_row(COLUMNS)
        _sheet = ws
    return _sheet


def neutralize(value):
    # Anyone on the internet can fill in the form. Text like =HYPERLINK(...) would run as a
    # formula when the owner opens the CSV in Excel, so it gets a leading quote. Phone
    # numbers like "+91 98..." start with + too, but they have no letters, so they're left alone.
    text = str(value)
    if text[:1] in ("=", "@", "\t", "\r") or (text[:1] in ("+", "-") and re.search(r"[A-Za-z(]", text)):
        return "'" + text
    return text


def save_lead(lead):
    row = [lead.get(c, "") for c in COLUMNS]

    if backend_name() == "google_sheets":
        # RAW stores the text as typed, so a submitted "=..." can't become a formula in the sheet
        _worksheet().append_row(row, value_input_option="RAW")
        return

    row = [neutralize(v) for v in row]

    path = Path(os.getenv("LEADS_CSV") or Path(__file__).parent / "data" / "leads.csv")
    path.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        new_file = not path.exists()
        with open(path, "a", newline="", encoding="utf-8-sig" if new_file else "utf-8") as f:
            w = csv.writer(f)
            if new_file:
                w.writerow(COLUMNS)
            w.writerow(row)
