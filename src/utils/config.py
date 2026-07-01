import os
from dataclasses import dataclass
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")


# ── Provedores de IA (selecionáveis por env AI_PROVIDER) ───────────────────────
# Os 4 provedores expõem um endpoint OpenAI-compatible, então o bot usa o mesmo
# SDK `openai` pra todos: muda só a chave (env própria), o base_url, o modelo e
# alguns parâmetros da chamada. `default_model` = o MAIS BARATO de cada provedor
# adequado pra gerar a proposta em JSON (preços no GUIA.md). Campos por provedor:
#   key_envs      – envs aceitas pra chave (1ª preenchida vence)
#   model_env     – env pra trocar o modelo só desse provedor
#   base_url      – endpoint OpenAI-compatible
#   default_model – modelo mais barato (padrão)
#   json_object   – aceita response_format=json_object nativo? (senão, regex extrai)
#   token_param   – nome do kwarg de teto de saída ("max_tokens" ou, na família
#                   GPT-5, "max_completion_tokens")
#   send_temperature – se manda temperatura (GPT-5 só aceita o default → False)
#   extra_body    – kwargs extras no corpo (reasoning_effort do OpenAI, enable_thinking
#                   do Qwen p/ ficar em modo não-thinking, onde o json_object funciona)
# Overrides por env: AI_PROVIDER (provedor), <PROVIDER>_MODEL (modelo do provedor),
# AI_MODEL (modelo global, ganha de todos), AI_BASE_URL (endpoint custom).
AI_PROVIDERS: dict[str, dict] = {
    "deepseek": dict(
        key_envs=("DEEPSEEK_API_KEY",),
        model_env="DEEPSEEK_MODEL",
        base_url="https://api.deepseek.com",
        default_model="deepseek-v4-flash",
        json_object=True,
        token_param="max_tokens",
        send_temperature=True,
        extra_body={},
        keys_url="https://platform.deepseek.com/api_keys",
    ),
    "openai": dict(
        key_envs=("OPENAI_API_KEY",),
        model_env="OPENAI_MODEL",
        base_url="https://api.openai.com/v1",
        default_model="gpt-5-nano",
        json_object=True,
        token_param="max_completion_tokens",  # família GPT-5 rejeita max_tokens
        send_temperature=False,                # GPT-5 só aceita temperatura=1 (default) → omite
        extra_body={"reasoning_effort": "minimal"},  # não paga tokens de raciocínio em JSON curto
        keys_url="https://platform.openai.com/api-keys",
    ),
    "google": dict(
        key_envs=("GOOGLE_API_KEY", "GEMINI_API_KEY"),
        model_env="GOOGLE_MODEL",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        default_model="gemini-2.5-flash-lite",
        json_object=True,
        token_param="max_tokens",
        send_temperature=True,
        extra_body={},
        keys_url="https://aistudio.google.com/app/apikey",
    ),
    "qwen": dict(
        key_envs=("QWEN_API_KEY", "DASHSCOPE_API_KEY"),
        model_env="QWEN_MODEL",
        base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        default_model="qwen-flash",
        json_object=True,
        token_param="max_tokens",
        send_temperature=True,
        extra_body={"enable_thinking": False},  # json_object só funciona em modo não-thinking
        keys_url="https://bailian.console.alibabacloud.com/?tab=model#/api-key",
    ),
}
DEFAULT_AI_PROVIDER = "deepseek"


def _resolve_provider() -> dict:
    """Lê AI_PROVIDER (+ overrides) e devolve o dict de configuração da IA ativa.
    A env da chave é específica do provedor; modelo/base_url têm overrides opcionais."""
    provider = (os.getenv("AI_PROVIDER") or DEFAULT_AI_PROVIDER).strip().lower()
    if provider not in AI_PROVIDERS:
        provider = DEFAULT_AI_PROVIDER
    cfg = AI_PROVIDERS[provider]

    api_key = ""
    for env in cfg["key_envs"]:
        if os.getenv(env):
            api_key = os.getenv(env, "")
            break

    return dict(
        provider=provider,
        api_key=api_key,
        base_url=os.getenv("AI_BASE_URL") or cfg["base_url"],
        model=os.getenv(cfg["model_env"]) or os.getenv("AI_MODEL") or cfg["default_model"],
        json_object=bool(cfg["json_object"]),
        token_param=cfg.get("token_param", "max_tokens"),
        send_temperature=bool(cfg.get("send_temperature", True)),
        extra_body=dict(cfg.get("extra_body") or {}),
    )


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
    # IA (provedor selecionável por AI_PROVIDER; tudo via SDK openai-compatible)
    ai_provider: str
    ai_api_key: str
    ai_base_url: str
    ai_model: str
    ai_json_object: bool
    ai_token_param: str
    ai_send_temperature: bool
    ai_extra_body: dict
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

        ai = _resolve_provider()

        return cls(
            ai_provider=ai["provider"],
            ai_api_key=ai["api_key"],
            ai_base_url=ai["base_url"],
            ai_model=ai["model"],
            ai_json_object=ai["json_object"],
            ai_token_param=ai["token_param"],
            ai_send_temperature=ai["send_temperature"],
            ai_extra_body=ai["extra_body"],
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

    def ai_summary(self) -> str:
        """Linha amigável pra logar/exibir o provedor de IA ativo."""
        key = "ok" if self.ai_api_key else "FALTANDO"
        return (
            f"provider={self.ai_provider} | modelo={self.ai_model} "
            f"| json_object={'on' if self.ai_json_object else 'off'} | chave={key}"
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
