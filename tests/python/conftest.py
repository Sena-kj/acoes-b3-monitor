"""
conftest.py — Fixtures compartilhadas pelos testes do acoes-b3-monitor.

Payloads baseados nos dados reais do research (api-contract.yaml).
Todas as chamadas externas sao mockadas — zero rede real nos testes.
"""

from __future__ import annotations

import sys
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

# Garante que coordination/ (com _contract_types.py) esta no PYTHONPATH
PROJECT_ROOT = Path(__file__).parent.parent.parent
COORDINATION_DIR = PROJECT_ROOT / "coordination"
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(COORDINATION_DIR))

from acoes_b3_monitor.types import (
    AlertEvent,
    AlertRule,
    DailyBriefing,
    NewsAnalysis,
    NewsItem,
    NewsSource,
    Quote,
    Sentiment,
    Settings,
    TickerConfig,
    TriggerType,
)


# ---------------------------------------------------------------------------
# Helpers de datetime
# ---------------------------------------------------------------------------

FAKE_MARKET_TIME = datetime(2026, 5, 24, 18, 30, 0, tzinfo=timezone.utc)
FAKE_FETCHED_AT = datetime(2026, 5, 24, 18, 45, 22, tzinfo=timezone.utc)
FAKE_DELAY = (FAKE_FETCHED_AT - FAKE_MARKET_TIME).total_seconds() / 60  # 15.37


# ---------------------------------------------------------------------------
# Payload brapi real (do research-report.md e api-contract.yaml)
# ---------------------------------------------------------------------------

BRAPI_RESPONSE_PAYLOAD = {
    "results": [
        {
            "symbol": "PETR4",
            "longName": "Petroleo Brasileiro SA Pfd",
            "currency": "BRL",
            "regularMarketPrice": 44.48,
            "regularMarketDayHigh": 44.75,
            "regularMarketDayLow": 43.87,
            "regularMarketChange": -0.47,
            "regularMarketChangePercent": -1.05,
            "regularMarketTime": "2026-05-22T21:30:30.000Z",
            "regularMarketPreviousClose": 44.42,
            "regularMarketOpen": 44.74,
            "regularMarketVolume": 39610500,
            "marketCap": 613085621299,
        },
        {
            "symbol": "VALE3",
            "longName": "Vale S.A.",
            "currency": "BRL",
            "regularMarketPrice": 62.10,
            "regularMarketDayHigh": 62.80,
            "regularMarketDayLow": 61.50,
            "regularMarketChange": 0.18,
            "regularMarketChangePercent": 0.30,
            "regularMarketTime": "2026-05-22T21:30:30.000Z",
            "regularMarketPreviousClose": 61.92,
            "regularMarketOpen": 62.00,
            "regularMarketVolume": 15000000,
            "marketCap": 280000000000,
        },
        {
            "symbol": "ITUB4",
            "longName": "Itau Unibanco Holding SA Pfd",
            "currency": "BRL",
            "regularMarketPrice": 35.20,
            "regularMarketDayHigh": 35.50,
            "regularMarketDayLow": 34.90,
            "regularMarketChange": -0.17,
            "regularMarketChangePercent": -0.50,
            "regularMarketTime": "2026-05-22T21:30:30.000Z",
            "regularMarketPreviousClose": 35.37,
            "regularMarketOpen": 35.40,
            "regularMarketVolume": 12000000,
            "marketCap": 180000000000,
        },
        {
            "symbol": "MGLU3",
            "longName": "Magazine Luiza SA",
            "currency": "BRL",
            "regularMarketPrice": 12.50,
            "regularMarketDayHigh": 12.80,
            "regularMarketDayLow": 12.20,
            "regularMarketChange": 0.15,
            "regularMarketChangePercent": 1.20,
            "regularMarketTime": "2026-05-22T21:30:30.000Z",
            "regularMarketPreviousClose": 12.35,
            "regularMarketOpen": 12.40,
            "regularMarketVolume": 20000000,
            "marketCap": 10000000000,
        },
    ],
    "requestedAt": "2026-05-24T18:45:22.014Z",
    "took": 140,
}


# ---------------------------------------------------------------------------
# Fixtures de Quote
# ---------------------------------------------------------------------------

@pytest.fixture
def quote_petr4() -> Quote:
    return Quote(
        symbol="PETR4",
        price=44.48,
        change=-0.47,
        change_pct=-1.05,
        day_high=44.75,
        day_low=43.87,
        previous_close=44.42,
        volume=39610500,
        market_time=FAKE_MARKET_TIME,
        fetched_at=FAKE_FETCHED_AT,
        delay_minutes=FAKE_DELAY,
        currency="BRL",
    )


@pytest.fixture
def quote_vale3() -> Quote:
    return Quote(
        symbol="VALE3",
        price=62.10,
        change=0.18,
        change_pct=0.30,
        day_high=62.80,
        day_low=61.50,
        previous_close=61.92,
        volume=15000000,
        market_time=FAKE_MARKET_TIME,
        fetched_at=FAKE_FETCHED_AT,
        delay_minutes=FAKE_DELAY,
        currency="BRL",
    )


@pytest.fixture
def quote_mglu3_below_trigger() -> Quote:
    """MGLU3 a 13.49 — abaixo do gatilho PCT 10% (threshold=13.50)."""
    return Quote(
        symbol="MGLU3",
        price=13.49,
        change=-0.10,
        change_pct=-0.74,
        day_high=13.60,
        day_low=13.40,
        previous_close=13.59,
        volume=20000000,
        market_time=FAKE_MARKET_TIME,
        fetched_at=FAKE_FETCHED_AT,
        delay_minutes=FAKE_DELAY,
        currency="BRL",
    )


@pytest.fixture
def quote_petr4_below_trigger() -> Quote:
    """PETR4 a 41.20 — abaixo do gatilho PRICE 42.00."""
    return Quote(
        symbol="PETR4",
        price=41.20,
        change=-1.28,
        change_pct=-3.01,
        day_high=42.50,
        day_low=41.00,
        previous_close=42.48,
        volume=39610500,
        market_time=FAKE_MARKET_TIME,
        fetched_at=FAKE_FETCHED_AT,
        delay_minutes=FAKE_DELAY,
        currency="BRL",
    )


# ---------------------------------------------------------------------------
# Fixtures de AlertRule
# ---------------------------------------------------------------------------

@pytest.fixture
def rule_petr4_price() -> AlertRule:
    """CA-03: gatilho absoluto PETR4 price:42.00"""
    return AlertRule(
        ticker="PETR4",
        trigger_type=TriggerType.PRICE,
        trigger_value=42.00,
        buy_price=45.00,
    )


@pytest.fixture
def rule_vale3_price_high() -> AlertRule:
    """CA-05: gatilho price:55.00 (nao dispara com price=62.00)"""
    return AlertRule(
        ticker="VALE3",
        trigger_type=TriggerType.PRICE,
        trigger_value=55.00,
        buy_price=60.00,
    )


@pytest.fixture
def rule_mglu3_pct() -> AlertRule:
    """CA-04: gatilho pct:10 — threshold = 15.00 * 0.90 = 13.50"""
    return AlertRule(
        ticker="MGLU3",
        trigger_type=TriggerType.PCT,
        trigger_value=10.0,
        buy_price=15.00,
    )


# ---------------------------------------------------------------------------
# Fixture de Settings
# ---------------------------------------------------------------------------

@pytest.fixture
def settings() -> Settings:
    return Settings(
        tickers=["PETR4", "VALE3", "ITUB4", "MGLU3"],
        telegram_bot_token="test_bot_token",
        telegram_chat_id="123456789",
        anthropic_api_key="test_anthropic_key",
        ticker_configs={
            "PETR4": TickerConfig(
                ticker="PETR4",
                buy_price=45.00,
                alert_rule=AlertRule(
                    ticker="PETR4",
                    trigger_type=TriggerType.PRICE,
                    trigger_value=42.00,
                    buy_price=45.00,
                ),
            ),
            "VALE3": TickerConfig(
                ticker="VALE3",
                buy_price=60.00,
                alert_rule=AlertRule(
                    ticker="VALE3",
                    trigger_type=TriggerType.PCT,
                    trigger_value=5.0,
                    buy_price=60.00,
                ),
            ),
            "ITUB4": TickerConfig(
                ticker="ITUB4",
                buy_price=34.00,
                alert_rule=AlertRule(
                    ticker="ITUB4",
                    trigger_type=TriggerType.PRICE,
                    trigger_value=33.00,
                    buy_price=34.00,
                ),
            ),
            "MGLU3": TickerConfig(
                ticker="MGLU3",
                buy_price=15.00,
                alert_rule=AlertRule(
                    ticker="MGLU3",
                    trigger_type=TriggerType.PCT,
                    trigger_value=10.0,
                    buy_price=15.00,
                ),
            ),
        },
        brapi_token=None,
        briefing_time="08:00",
        market_open="09:45",
        market_close="17:30",
        alert_cooldown_minutes=60,
        news_fetch_interval_minutes=30,
        quote_poll_interval_minutes=5,
    )


# ---------------------------------------------------------------------------
# Fixture de NewsItem
# ---------------------------------------------------------------------------

@pytest.fixture
def news_item_vale3() -> NewsItem:
    return NewsItem(
        guid="infomoney:https://www.infomoney.com.br/noticias/vale-paralisacao-123",
        title="Vale anuncia paralisacao emergencial em mina de MG",
        source=NewsSource.INFOMONEY,
        published_at=datetime(2026, 5, 24, 9, 14, 0, tzinfo=timezone.utc),
        url="https://www.infomoney.com.br/noticias/vale-paralisacao-123",
        tickers=["VALE3"],
        body="A mineradora paralisou operacoes em mina apos incidente tecnico. O evento pode afetar volumes de producao no curto prazo.",
        encoding_source="latin-1",
    )


@pytest.fixture
def news_item_cvm() -> NewsItem:
    return NewsItem(
        guid="cvm_ipe:001023IPE20260524001",
        title="Vale anuncia resultado operacional do 1T26",
        source=NewsSource.CVM_IPE,
        published_at=datetime(2026, 5, 24, 9, 14, 0, tzinfo=timezone.utc),
        url="https://www.rad.cvm.gov.br/ENET/frmDownloadDocumento.aspx?Tipo=PDF&protocolo=001023",
        tickers=["VALE3"],
        cvm_protocolo="001023IPE20260524001",
        cvm_link_download="https://www.rad.cvm.gov.br/ENET/frmDownloadDocumento.aspx?Tipo=PDF&protocolo=001023",
        encoding_source="latin-1",
    )


# ---------------------------------------------------------------------------
# Fixture de NewsAnalysis
# ---------------------------------------------------------------------------

@pytest.fixture
def news_analysis_vale3(news_item_vale3: NewsItem) -> NewsAnalysis:
    return NewsAnalysis(
        news_guid=news_item_vale3.guid,
        ticker="VALE3",
        sentiment=Sentiment.NEGATIVO,
        summary="Vale interrompeu operacoes em uma mina de MG por motivo tecnico. O incidente pode afetar volumes de producao no curto prazo.",
        analyzed_at=datetime(2026, 5, 24, 9, 30, 0, tzinfo=timezone.utc),
        model="claude-haiku-4-5-20251001",
        input_tokens=120,
        output_tokens=48,
    )


# ---------------------------------------------------------------------------
# Fixture de DB temporario
# ---------------------------------------------------------------------------

@pytest.fixture
async def tmp_db(tmp_path) -> str:
    """Banco SQLite temporario inicializado."""
    from acoes_b3_monitor.storage import init_db
    db_path = str(tmp_path / "test.db")
    await init_db(db_path)
    return db_path
