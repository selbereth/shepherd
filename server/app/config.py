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
MAX_TEXT_CHARS = 20000
