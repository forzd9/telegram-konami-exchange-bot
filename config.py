# config.py
import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


def required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


BOT_TOKEN = required_env("BOT_TOKEN")
EMAIL_ADDRESS = required_env("EMAIL_ADDRESS")
EMAIL_PASSWORD = required_env("EMAIL_PASSWORD")
IMAP_SERVER = os.getenv("IMAP_SERVER", "imap.gmail.com")
IMAP_PORT = int(os.getenv("IMAP_PORT", "993"))


@dataclass(frozen=True)
class Config:
    ADMIN_IDS: list[int] = [6891530912]
    CHANNEL_ID: int = -1002514428576
    BOT_TOKEN: str = BOT_TOKEN
    DB_PATH: str = "deals.db"
    DEAL_TIMEOUT_MINUTES: int = 60
    OTP_WAIT_SECONDS: int = 300
    USER_RESPONSE_WAIT: int = 1800
    EMAIL_DOMAIN: str = os.getenv("EMAIL_DOMAIN", "gmail.com")
    EMAIL_ADDRESS: str = EMAIL_ADDRESS
    EMAIL_PASSWORD: str = EMAIL_PASSWORD
    BROWSER_HEADLESS: bool = os.getenv("BROWSER_HEADLESS", "true").lower() == "true"
    BROWSER_EXECUTABLE_PATH: str | None = os.getenv("BROWSER_EXECUTABLE_PATH")
    SESSIONS_DIR: str = os.getenv("SESSIONS_DIR", "browser_sessions")
    ENCRYPTION_KEY: str | None = os.getenv("ENCRYPTION_KEY")
