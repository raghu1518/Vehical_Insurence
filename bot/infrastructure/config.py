from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT_DIR / "configs"
SETTINGS_PATH = CONFIG_DIR / "settings.json"


@dataclass
class LLMSettings:
    provider: str
    model: str
    base_url: str
    api_key: str
    timeout_s: int


@dataclass
class Settings:
    default_language: str
    default_system_prompt_id: str
    timezone: str
    llm: LLMSettings
    postgres: "PostgresSettings"
    data_paths: "DataPaths"
    logging: "LoggingSettings"
    telegram: "TelegramSettings"
    session: "SessionSettings"


@dataclass
class PostgresSettings:
    user: str
    password: str
    host: str
    port: int
    db: str


@dataclass
class DataPaths:
    hospitals_xlsx: Path
    garages_xlsx: Path
    faqs_dir: Path


@dataclass
class LoggingSettings:
    dir: Path
    level: str


@dataclass
class TelegramSettings:
    bot_token: str
    chat_id: str
    sms_enabled: bool


@dataclass
class SessionSettings:
    expire_minutes: int
    summary_max_chars: int


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _select_api_key(provider: str) -> str:
    if provider == "openai":
        return os.getenv("OPENAI_API_KEY", "") or os.getenv("LLM_API_KEY", "")
    if provider == "groq":
        return os.getenv("GROQ_API_KEY", "") or os.getenv("LLM_API_KEY", "")
    if provider == "claude":
        return os.getenv("ANTHROPIC_API_KEY", "") or os.getenv("LLM_API_KEY", "")
    if provider == "ollama":
        return ""
    return os.getenv("LLM_API_KEY", "")


def load_settings() -> Settings:
    data = _read_json(SETTINGS_PATH)

    default_language = os.getenv("DEFAULT_LANGUAGE", data.get("default_language", "hi"))
    default_system_prompt_id = os.getenv(
        "SYSTEM_PROMPT_ID", data.get("default_system_prompt_id", "core-hi")
    )
    timezone = os.getenv("TIMEZONE", data.get("timezone", "Asia/Kolkata"))

    llm_data = data.get("llm", {})
    provider = os.getenv("LLM_PROVIDER", llm_data.get("provider", "openai"))
    model = os.getenv("LLM_MODEL", llm_data.get("model", "gpt-4o-mini"))
    base_url = os.getenv("LLM_BASE_URL", llm_data.get("base_url", ""))
    if not base_url:
        base_urls = data.get("llm_base_urls", {})
        base_url = base_urls.get(provider, "")
    timeout_s = int(os.getenv("LLM_TIMEOUT", "30"))
    api_key = _select_api_key(provider) or llm_data.get("api_key", "")

    pg_data = data.get("postgres", {})
    pg_user = os.getenv("POSTGRES_USER", pg_data.get("user", ""))
    pg_password = os.getenv("POSTGRES_PASSWORD", pg_data.get("password", ""))
    pg_host = os.getenv("POSTGRES_HOST", pg_data.get("host", "localhost"))
    pg_port = int(os.getenv("POSTGRES_PORT", pg_data.get("port", 5432)))
    pg_db = os.getenv("POSTGRES_DB", pg_data.get("db", "postgres"))

    data_paths = data.get("data_paths", {})
    def _resolve_path(value: str) -> Path:
        path = Path(value)
        if not path.is_absolute():
            return ROOT_DIR / path
        return path

    hospitals_path = _resolve_path(
        os.getenv("HOSPITALS_XLSX", data_paths.get("hospitals_xlsx", "data/hospitals.xlsx"))
    )
    garages_path = _resolve_path(
        os.getenv("GARAGES_XLSX", data_paths.get("garages_xlsx", "data/garages.xlsx"))
    )
    faqs_dir = _resolve_path(os.getenv("FAQS_DIR", data_paths.get("faqs_dir", "data/faqs")))

    logging_data = data.get("logging", {})
    log_dir = _resolve_path(os.getenv("LOG_DIR", logging_data.get("dir", "logs")))
    log_level = os.getenv("LOG_LEVEL", logging_data.get("level", "INFO"))

    telegram_data = data.get("telegram", {})
    telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not telegram_bot_token:
        telegram_bot_token = telegram_data.get("bot_token", "")
    telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not telegram_chat_id:
        telegram_chat_id = telegram_data.get("chat_id", "")
    sms_enabled_raw = os.getenv("TELEGRAM_SMS_ENABLED", str(telegram_data.get("sms_enabled", True)))
    sms_enabled = str(sms_enabled_raw).strip().lower() in {"1", "true", "yes", "y", "on"}

    session_data = data.get("session", {})
    expire_minutes = int(os.getenv("SESSION_EXPIRE_MINUTES", session_data.get("expire_minutes", 30)))
    summary_max_chars = int(os.getenv("SESSION_SUMMARY_MAX_CHARS", session_data.get("summary_max_chars", 1000)))

    return Settings(
        default_language=default_language,
        default_system_prompt_id=default_system_prompt_id,
        timezone=timezone,
        llm=LLMSettings(
            provider=provider,
            model=model,
            base_url=base_url,
            api_key=api_key,
            timeout_s=timeout_s,
        ),
        postgres=PostgresSettings(
            user=pg_user,
            password=pg_password,
            host=pg_host,
            port=pg_port,
            db=pg_db,
        ),
        data_paths=DataPaths(
            hospitals_xlsx=hospitals_path,
            garages_xlsx=garages_path,
            faqs_dir=faqs_dir,
        ),
        logging=LoggingSettings(
            dir=log_dir,
            level=log_level,
        ),
        telegram=TelegramSettings(
            bot_token=telegram_bot_token,
            chat_id=str(telegram_chat_id or ""),
            sms_enabled=sms_enabled,
        ),
        session=SessionSettings(
            expire_minutes=expire_minutes,
            summary_max_chars=summary_max_chars,
        ),
    )


SETTINGS = load_settings()


def reload_settings() -> Settings:
    global SETTINGS
    SETTINGS = load_settings()
    return SETTINGS
