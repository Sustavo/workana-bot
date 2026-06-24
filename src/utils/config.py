import os
from dataclasses import dataclass
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")


# ── Perfis de velocidade (anti-ban) ───────────────────────────────────────────
# Cada perfil define a faixa de delay entre ações, a pausa longa ocasional e o
# teto de ações por hora. O usuário escolhe via SPEED_PROFILE no .env ou a flag
# CLI --speed. Overrides individuais (MIN_DELAY_SECONDS etc.) ganham do preset.
SPEED_PRESETS: dict[str, dict] = {
    "conservador": dict(
        min_delay=4.0, max_delay=10.0,
        long_pause_chance=0.18, long_pause_min=25.0, long_pause_max=70.0,
        max_actions_per_hour=40,
    ),
    "equilibrado": dict(
        min_delay=2.5, max_delay=6.0,
        long_pause_chance=0.12, long_pause_min=15.0, long_pause_max=45.0,
        max_actions_per_hour=90,
    ),
    "rapido": dict(
        min_delay=0.5, max_delay=1.5,
        long_pause_chance=0.0, long_pause_min=0.0, long_pause_max=0.0,
        max_actions_per_hour=0,
    ),
}
DEFAULT_SPEED_PROFILE = "equilibrado"


def _env_float(name: str, default: float) -> float:
    v = os.getenv(name)
    return float(v) if v not in (None, "") else float(default)


def _env_int(name: str, default: int) -> int:
    v = os.getenv(name)
    return int(v) if v not in (None, "") else int(default)


@dataclass(frozen=True)
class Settings:
    deepseek_api_key: str
    deepseek_model: str
    deepseek_base_url: str
    workana_jobs_url: str
    workana_user_id: str
    chrome_profile_dir: Path
    headless: bool
    max_drafts_per_run: int
    # velocidade / anti-ban
    speed_profile: str
    min_delay_seconds: float
    max_delay_seconds: float
    long_pause_chance: float
    long_pause_min_seconds: float
    long_pause_max_seconds: float
    max_actions_per_hour: int
    # envio / guard
    submit_redirect_timeout_ms: int
    guard_enabled: bool
    # infra
    database_path: Path
    log_level: str
    log_file: Path
    fill_delivery_time: bool

    @classmethod
    def load(cls, speed_override: str | None = None) -> "Settings":
        profile = (speed_override or os.getenv("SPEED_PROFILE") or DEFAULT_SPEED_PROFILE).strip().lower()
        if profile not in SPEED_PRESETS:
            profile = DEFAULT_SPEED_PROFILE
        preset = SPEED_PRESETS[profile]

        return cls(
            deepseek_api_key=os.getenv("DEEPSEEK_API_KEY", ""),
            deepseek_model=os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash"),
            deepseek_base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
            workana_jobs_url=os.getenv(
                "WORKANA_JOBS_URL",
                "https://www.workana.com/jobs?language=en%2Cpt",
            ),
            workana_user_id=os.getenv("WORKANA_USER_ID", ""),
            chrome_profile_dir=ROOT / os.getenv("CHROME_PROFILE_DIR", "./data/chrome-profile"),
            headless=os.getenv("HEADLESS", "false").lower() == "true",
            max_drafts_per_run=_env_int("MAX_DRAFTS_PER_RUN", 8),
            # velocidade: preset como default, env individual sobrepõe
            speed_profile=profile,
            min_delay_seconds=_env_float("MIN_DELAY_SECONDS", preset["min_delay"]),
            max_delay_seconds=_env_float("MAX_DELAY_SECONDS", preset["max_delay"]),
            long_pause_chance=_env_float("LONG_PAUSE_CHANCE", preset["long_pause_chance"]),
            long_pause_min_seconds=_env_float("LONG_PAUSE_MIN_SECONDS", preset["long_pause_min"]),
            long_pause_max_seconds=_env_float("LONG_PAUSE_MAX_SECONDS", preset["long_pause_max"]),
            max_actions_per_hour=_env_int("MAX_ACTIONS_PER_HOUR", preset["max_actions_per_hour"]),
            submit_redirect_timeout_ms=_env_int("SUBMIT_REDIRECT_TIMEOUT_MS", 25_000),
            guard_enabled=os.getenv("GUARD_ENABLED", "true").lower() == "true",
            database_path=ROOT / os.getenv("DATABASE_PATH", "./data/workana.db"),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            log_file=ROOT / os.getenv("LOG_FILE", "./data/logs/run.log"),
            fill_delivery_time=os.getenv("FILL_DELIVERY_TIME", "false").lower() == "true",
        )

    def speed_summary(self) -> str:
        """Linha amigável pra logar/exibir o perfil ativo."""
        cap = f"{self.max_actions_per_hour}/h" if self.max_actions_per_hour else "sem teto"
        pause = (
            f"{self.long_pause_min_seconds:.0f}-{self.long_pause_max_seconds:.0f}s @ {self.long_pause_chance:.0%}"
            if self.long_pause_chance > 0 else "off"
        )
        return (
            f"perfil={self.speed_profile} | delay {self.min_delay_seconds:.1f}-{self.max_delay_seconds:.1f}s "
            f"| pausa longa {pause} | teto {cap}"
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
