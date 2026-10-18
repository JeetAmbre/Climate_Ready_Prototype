"""Email notification service for ClimateReady contact inquiries."""
import html
import json
import logging
import smtplib
import threading
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import config

logger = logging.getLogger("climateready.mailer")
MESSAGES_LOG_FILE = config.BASE_DIR / "data" / "contact_messages.jsonl"


def _save_message_to_disk(entry: dict) -> None:
    try:
        MESSAGES_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(MESSAGES_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as exc:
        logger.warning(f"Failed to record contact message to disk: {exc}")


def _send_email_smtp(entry: dict) -> bool:
    user = (getattr(config, "MAIL_USERNAME", "") or "").strip()
    pwd = (getattr(config, "MAIL_PASSWORD", "") or "").strip()
    to_email = (getattr(config, "MAIL_TO", "") or user or "jeetambre090@gmail.com").strip()

    if not user or not pwd:
        logger.info(
            f"[CONTACT] Submission from {entry.get('name')} <{entry.get('email')}> saved to disk. "
            "(MAIL_USERNAME and MAIL_PASSWORD not configured; email dispatch skipped)"
        )
        return False

    name = entry.get("name", "Website Visitor")
    sender_email = entry.get("email", "unknown")
    org = entry.get("org") or "Not provided"
    message_text = entry.get("message", "")
    timestamp = entry.get("timestamp", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"))

    subject = f"[ClimateReady] New message from {name}"

    # Plain text version
    text_content = (
        f"You received a new inquiry from the ClimateReady contact form:\n\n"
        f"Name: {name}\n"
        f"Email: {sender_email}\n"
        f"Organisation: {org}\n"
        f"Time: {timestamp}\n\n"
        f"Message:\n"
        f"--------------------------------------------------\n"
        f"{message_text}\n"
        f"--------------------------------------------------\n\n"
        f"Reply directly to this email to respond to {name}."
    )

    # HTML version
    escaped_msg = html.escape(message_text).replace("\n", "<br>")
    html_content = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; color: #1e293b; background: #f8fafc; padding: 20px; }}
    .card {{ max-width: 580px; margin: 0 auto; background: #ffffff; border-radius: 12px; border: 1px solid #e2e8f0; overflow: hidden; }}
    .header {{ background: #0f172a; color: #ffffff; padding: 20px 24px; }}
    .header h2 {{ margin: 0; font-size: 1.25rem; font-weight: 600; }}
    .header p {{ margin: 4px 0 0; color: #94a3b8; font-size: 0.875rem; }}
    .body {{ padding: 24px; }}
    .field {{ margin-bottom: 16px; }}
    .label {{ font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.05em; color: #64748b; font-weight: 600; margin-bottom: 4px; }}
    .value {{ font-size: 1rem; color: #0f172a; }}
    .message-box {{ background: #f1f5f9; border-left: 4px solid #0284c7; padding: 16px; border-radius: 6px; font-size: 0.95rem; line-height: 1.6; margin-top: 16px; }}
    .footer {{ padding: 16px 24px; background: #f8fafc; border-top: 1px solid #e2e8f0; font-size: 0.8125rem; color: #64748b; text-align: center; }}
  </style>
</head>
<body>
  <div class="card">
    <div class="header">
      <h2>New Message · ClimateReady</h2>
      <p>Received via climateready.in/contact</p>
    </div>
    <div class="body">
      <div class="field">
        <div class="label">Sender Name</div>
        <div class="value"><strong>{html.escape(name)}</strong></div>
      </div>
      <div class="field">
        <div class="label">Email Address</div>
        <div class="value"><a href="mailto:{html.escape(sender_email)}">{html.escape(sender_email)}</a></div>
      </div>
      <div class="field">
        <div class="label">Organisation</div>
        <div class="value">{html.escape(org)}</div>
      </div>
      <div class="field">
        <div class="label">Message</div>
        <div class="message-box">{escaped_msg}</div>
      </div>
    </div>
    <div class="footer">
      Reply directly to this email to respond to {html.escape(name)}.
    </div>
  </div>
</body>
</html>"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"ClimateReady <{user}>"
    msg["To"] = to_email
    msg["Reply-To"] = sender_email

    msg.attach(MIMEText(text_content, "plain", "utf-8"))
    msg.attach(MIMEText(html_content, "html", "utf-8"))

    try:
        server = smtplib.SMTP(getattr(config, "MAIL_SERVER", "smtp.gmail.com"), getattr(config, "MAIL_PORT", 587), timeout=12)
        if getattr(config, "MAIL_USE_TLS", True):
            server.starttls()
        server.login(user, pwd)
        server.send_message(msg)
        server.quit()
        logger.info(f"[CONTACT] Email dispatched successfully to {to_email} for {sender_email}")
        return True
    except Exception as exc:
        logger.error(f"[CONTACT] Failed to send email via SMTP: {exc}")
        return False


def handle_contact_submission(data: dict, client_ip: str = "") -> None:
    """Save message to disk and trigger background email dispatch."""
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "ip": client_ip,
        "name": (data.get("name") or "").strip(),
        "email": (data.get("email") or "").strip(),
        "org": (data.get("org") or "").strip(),
        "message": (data.get("message") or "").strip(),
    }
    _save_message_to_disk(entry)
    threading.Thread(target=_send_email_smtp, args=(entry,), daemon=True).start()
