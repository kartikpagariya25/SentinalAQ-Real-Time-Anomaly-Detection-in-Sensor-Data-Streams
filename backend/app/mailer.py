import os
import smtplib
import ssl
import threading
import time
from email.message import EmailMessage

import pandas as pd

from .ingest import Ingestor, Store, period_window
from .model import load_bundle
from .report_pdf import build_report_pdf


def _cfg():
    return {
        "host": os.environ.get("SMTP_HOST"),
        "port": int(os.environ.get("SMTP_PORT", "587")),
        "user": os.environ.get("SMTP_USER"),
        "password": os.environ.get("SMTP_PASS"),
        "sender": os.environ.get("REPORT_FROM", os.environ.get("SMTP_USER", "")),
        "to": [a.strip() for a in os.environ.get("REPORT_TO", "").split(",") if a.strip()],
    }


def _body(s):
    n = max(s["readings"], 1)
    lines = [
        f"SentinelAQ {s.get('period', 'day')} report",
        f"Window: {s.get('date') or s.get('start') + ' to ' + s.get('end')}",
        "",
        f"Readings         : {s['readings']:,}",
        f"Valid            : {s['valid']:,} ({s['valid'] / n * 100:.1f}%)",
        f"Invalid          : {s['invalid']:,} ({s['invalid'] / n * 100:.1f}%)",
        f"Review           : {s['review']:,} ({s['review'] / n * 100:.1f}%)",
        f"Pollution events : {s['pollution_events']:,}",
        f"Devices reporting: {s['devices_reporting']}",
        f"Mean confidence  : {s['mean_confidence']}",
    ]
    if s.get("faults_by_type"):
        lines += ["", "Rejected by fault type:"] + [f"  {k}: {v}" for k, v in s["faults_by_type"].items()]
    return "\n".join(lines)


def send_report(period="daily", anchor=None, to=None, ing=None):
    cfg = _cfg()
    to = to or cfg["to"]
    if not (cfg["host"] and cfg["sender"] and to):
        raise RuntimeError("email not configured: set SMTP_HOST, REPORT_FROM/SMTP_USER and REPORT_TO (or pass --to)")
    ing = ing or Ingestor(load_bundle(), Store())
    anchor = anchor or ing.store.span()[1] or pd.Timestamp.utcnow()
    start, end = period_window(period, anchor)
    s = ing.summary_range(start, end, period)

    msg = EmailMessage()
    msg["Subject"] = f"SentinelAQ {period} report | {s.get('start')}..{s.get('end')}"
    msg["From"] = cfg["sender"]
    msg["To"] = ", ".join(to)
    msg.set_content(_body(s))
    msg.add_attachment(build_report_pdf(s), maintype="application", subtype="pdf",
                       filename=f"sentinelaq_{period}_{pd.Timestamp(anchor).date()}.pdf")

    ctx = ssl.create_default_context()
    with smtplib.SMTP(cfg["host"], cfg["port"]) as srv:
        srv.starttls(context=ctx)
        if cfg["user"]:
            srv.login(cfg["user"], cfg["password"])
        srv.send_message(msg)
    return {"sent_to": to, "period": period, "readings": s["readings"]}


def start_scheduler(period="daily", at_hour=6):
    def loop():
        while True:
            now = pd.Timestamp.now()
            nxt = now.normalize() + pd.Timedelta(hours=at_hour)
            if nxt <= now:
                nxt += pd.Timedelta(days=1)
            time.sleep((nxt - now).total_seconds())
            try:
                send_report(period)
            except Exception as e:
                print(f"[mailer] skipped: {e}")

    t = threading.Thread(target=loop, daemon=True)
    t.start()
    return t
