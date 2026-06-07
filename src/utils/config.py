import os
from dataclasses import dataclass
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    google_api_key: str
    gemini_model: str
    workana_jobs_url: str
    workana_user_id: str
    chrome_profile_dir: Path
    headless: bool
    max_drafts_per_run: int
    min_delay_seconds: float
    max_delay_seconds: float
    database_path: Path
    log_level: str
    log_file: Path
    fill_delivery_time: bool

    @classmethod
    def load(cls) -> "Settings":
        return cls(
            google_api_key=os.getenv("GOOGLE_API_KEY", ""),
            gemini_model=os.getenv("GEMINI_MODEL", "gemini-2.0-flash"),
            workana_jobs_url=os.getenv(
                "WORKANA_JOBS_URL",
                "https://www.workana.com/jobs?language=en%2Cpt",
            ),
            workana_user_id=os.getenv("WORKANA_USER_ID", ""),
            chrome_profile_dir=ROOT / os.getenv("CHROME_PROFILE_DIR", "./data/chrome-profile"),
            headless=os.getenv("HEADLESS", "false").lower() == "true",
            max_drafts_per_run=int(os.getenv("MAX_DRAFTS_PER_RUN", "8")),
            min_delay_seconds=float(os.getenv("MIN_DELAY_SECONDS", "0.5")),
            max_delay_seconds=float(os.getenv("MAX_DELAY_SECONDS", "1.5")),
            database_path=ROOT / os.getenv("DATABASE_PATH", "./data/workana.db"),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            log_file=ROOT / os.getenv("LOG_FILE", "./data/logs/run.log"),
            fill_delivery_time=os.getenv("FILL_DELIVERY_TIME", "false").lower() == "true",
        )


def load_profile() -> dict:
    with open(ROOT / "config" / "profile.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_filters() -> dict:
    with open(ROOT / "config" / "filters.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_examples() -> str:
    path = ROOT / "Templates" / "proposals_examples.md"
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


PENDING_DIR = ROOT / "data" / "pending"
SENT_DIR = ROOT / "data" / "sent"
REJECTED_DIR = ROOT / "data" / "rejected"
