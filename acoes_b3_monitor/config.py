"""
config.py — Leitura de .env via Pydantic BaseSettings.

Expoe `get_settings()` (singleton lazy) que retorna objeto compativel com o
contrato Settings de coordination/_contract_types.py.
"""

from __future__ import annotations

import logging
from functools import lru_cache

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .types import AlertRule, Settings, TickerConfig, TriggerType

logger = logging.getLogger(__name__)

_FREE_TICKERS = {"PETR4", "VALE3", "ITUB4", "MGLU3"}

# Mapeamento ticker -> slug Money Times (extensivel)
TICKER_TO_MONEYTIMES_SLUG: dict[str, str] = {
    "PETR4": "petrobras",
    "VALE3": "vale",
    "ITUB4": "itau",
    "MGLU3": "magazine-luiza",
}

# Mapeamento ticker -> query Google News
TICKER_TO_GOOGLE_QUERY: dict[str, str] = {
    "PETR4": "Petrobras PETR4",
    "VALE3": "Vale VALE3",
    "ITUB4": "Itau ITUB4",
    "MGLU3": "Magazine Luiza MGLU3",
}

# Mapeamento ticker -> nome da companhia para match CVM
TICKER_TO_COMPANY_NAME: dict[str, str] = {
    "PETR4": "PETROBRAS",
    "VALE3": "VALE",
    "ITUB4": "ITAU",
    "MGLU3": "MAGAZINE LUIZA",
}


def _parse_trigger(raw: str, ticker: str, buy_price: float | None) -> AlertRule:
    """Parseia 'price:42.00' ou 'pct:5' para AlertRule."""
    raw = raw.strip()
    if ":" not in raw:
        raise ValueError(f"Formato invalido de ALERT_TRIGGER para {ticker}: '{raw}'. Use 'price:<valor>' ou 'pct:<n>'")
    kind, value_str = raw.split(":", 1)
    kind = kind.lower().strip()
    try:
        value = float(value_str.strip())
    except ValueError:
        raise ValueError(f"Valor invalido em ALERT_TRIGGER para {ticker}: '{value_str}'")

    if kind == "price":
        return AlertRule(ticker=ticker, trigger_type=TriggerType.PRICE, trigger_value=value, buy_price=buy_price)
    elif kind == "pct":
        if buy_price is None:
            raise ValueError(f"ALERT_TRIGGER pct para {ticker} requer {ticker}_BUY_PRICE definido")
        return AlertRule(ticker=ticker, trigger_type=TriggerType.PCT, trigger_value=value, buy_price=buy_price)
    else:
        raise ValueError(f"Tipo de trigger desconhecido '{kind}' para {ticker}. Use 'price' ou 'pct'")


class _EnvSettings(BaseSettings):
    """Leitura crua do .env. Nao use diretamente — use get_settings()."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="allow",  # permite PETR4_BUY_PRICE etc.
        case_sensitive=False,
    )

    tickers: str = Field(default="PETR4,VALE3,ITUB4,MGLU3")
    brapi_token: str | None = Field(default=None)
    telegram_bot_token: str = Field(default="")
    telegram_chat_id: str = Field(default="")
    anthropic_api_key: str = Field(default="")
    anthropic_model: str = Field(default="claude-haiku-4-5-20251001")
    briefing_time: str = Field(default="08:00")
    market_open: str = Field(default="09:45")
    market_close: str = Field(default="17:30")
    alert_cooldown_minutes: int = Field(default=60)
    news_fetch_interval_minutes: int = Field(default=30)
    quote_poll_interval_minutes: int = Field(default=5)
    db_path: str = Field(default="acoes_b3_monitor.db")

    @field_validator("brapi_token", mode="before")
    @classmethod
    def empty_str_to_none(cls, v: object) -> object:
        if isinstance(v, str) and v.strip() == "":
            return None
        return v


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Retorna Settings singleton. Lido uma vez e cacheado.
    Em testes, limpe o cache com get_settings.cache_clear().
    """
    env = _EnvSettings()

    tickers = [t.strip().upper() for t in env.tickers.split(",") if t.strip()]

    if not env.brapi_token:
        bad = [t for t in tickers if t not in _FREE_TICKERS]
        if bad:
            logger.warning(
                "Tickers %s nao estao na allowlist free do brapi (PETR4/VALE3/ITUB4/MGLU3). "
                "Defina BRAPI_TOKEN para usa-los.",
                bad,
            )

    ticker_configs: dict[str, TickerConfig] = {}
    raw_extra = env.model_extra or {}

    for ticker in tickers:
        buy_price_key = f"{ticker.lower()}_buy_price"
        trigger_key = f"{ticker.lower()}_alert_trigger"

        buy_price_raw = raw_extra.get(buy_price_key)
        buy_price: float | None = float(buy_price_raw) if buy_price_raw is not None else None

        trigger_raw = raw_extra.get(trigger_key)
        if trigger_raw and buy_price is not None:
            rule = _parse_trigger(str(trigger_raw), ticker, buy_price)
        elif trigger_raw:
            rule = _parse_trigger(str(trigger_raw), ticker, None)
        else:
            # Sem trigger configurado: cria regra dummy (price:0 nunca dispara)
            logger.warning("Nenhum ALERT_TRIGGER configurado para %s; alertas de preco desativados.", ticker)
            rule = AlertRule(ticker=ticker, trigger_type=TriggerType.PRICE, trigger_value=0.0, buy_price=buy_price)

        ticker_configs[ticker] = TickerConfig(
            ticker=ticker,
            buy_price=buy_price or 0.0,
            alert_rule=rule,
        )

    return Settings(
        tickers=tickers,
        telegram_bot_token=env.telegram_bot_token,
        telegram_chat_id=env.telegram_chat_id,
        anthropic_api_key=env.anthropic_api_key,
        ticker_configs=ticker_configs,
        brapi_token=env.brapi_token,
        briefing_time=env.briefing_time,
        market_open=env.market_open,
        market_close=env.market_close,
        alert_cooldown_minutes=env.alert_cooldown_minutes,
        news_fetch_interval_minutes=env.news_fetch_interval_minutes,
        quote_poll_interval_minutes=env.quote_poll_interval_minutes,
    )


def get_db_path() -> str:
    """Retorna caminho do SQLite, lido do env sem passar por Settings."""
    env = _EnvSettings()
    return env.db_path


def get_anthropic_model() -> str:
    """Retorna modelo Anthropic configurado."""
    env = _EnvSettings()
    return env.anthropic_model
