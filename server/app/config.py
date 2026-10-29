import os
from pathlib import Path

DATA_DIR = Path(os.environ.get("SHEPHERD_DATA", "data"))
DB_PATH = DATA_DIR / "shepherd.db"
ADMIN_KEY = os.environ.get("SHEPHERD_ADMIN_KEY", "")
# Score thresholds for page scanning.
WARN_SCORE = int(os.environ.get("SHEPHERD_WARN_SCORE", "5"))
BLOCK_SCORE = int(os.environ.get("SHEPHERD_BLOCK_SCORE", "10"))
# Ban the whole domain automatically when a page reaches BLOCK_SCORE.
AUTO_BAN = os.environ.get("SHEPHERD_AUTO_BAN", "false").lower() == "true"
# Seed the ban list with well-known adult/gambling domains (you can still unban any of them).
BUILTIN_BLOCKLIST = os.environ.get("SHEPHERD_BUILTIN_BLOCKLIST", "true").lower() == "true"
MAX_TEXT_CHARS = 20000

# ---- alerts ----
# Alert when a page reaches this verdict ("block" = only blocks, "warn" = warns and blocks).
ALERT_ON = os.environ.get("SHEPHERD_ALERT_ON", "block")
# Don't repeat the same alert (device + domain + verdict) within this many seconds.
ALERT_COOLDOWN = int(os.environ.get("SHEPHERD_ALERT_COOLDOWN", "600"))
# Alert when a device hasn't checked in for this many minutes (0 disables).
OFFLINE_MINUTES = int(os.environ.get("SHEPHERD_OFFLINE_MINUTES", "15"))
NTFY_URL = os.environ.get("SHEPHERD_NTFY_URL", "")  # e.g. https://ntfy.sh/my-secret-topic
NTFY_TOKEN = os.environ.get("SHEPHERD_NTFY_TOKEN", "")
WEBHOOK_URL = os.environ.get("SHEPHERD_WEBHOOK_URL", "")  # Slack/Discord/generic JSON
SMTP_HOST = os.environ.get("SHEPHERD_SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("SHEPHERD_SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SHEPHERD_SMTP_USER", "")
SMTP_PASS = os.environ.get("SHEPHERD_SMTP_PASS", "")
SMTP_FROM = os.environ.get("SHEPHERD_SMTP_FROM", "")
EMAIL_TO = os.environ.get("SHEPHERD_EMAIL_TO", "")
