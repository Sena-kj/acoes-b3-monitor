"""
Testes CA-01 e CA-02 — quote_collector.

CA-01: fetch_quotes retorna 4 objetos Quote com campos corretos.
CA-02: delay_minutes calculado corretamente e logado em INFO.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from acoes_b3_monitor.quote_collector import BrapiProvider, fetch_quotes
from acoes_b3_monitor.types import Quote, Settings
from tests.python.conftest import BRAPI_RESPONSE_PAYLOAD


class MockBrapiProvider:
    """Provider falso que retorna payload real do research sem rede."""

    async def fetch_quotes(self, tickers: list[str]) -> list[Quote]:
        from acoes_b3_monitor.quote_collector import BrapiProvider
        # Reutiliza o parser real do BrapiProvider com payload estatico
        provider = BrapiProvider.__new__(BrapiProvider)
        provider._token = None

        # Simula a logica de parse do BrapiProvider sem httpx
        data = BRAPI_RESPONSE_PAYLOAD
        fetched_at_str = data["requestedAt"]
        fetched_at = datetime.fromisoformat(fetched_at_str.replace("Z", "+00:00"))

        quotes = []
        for item in data["results"]:
            if item["symbol"] not in tickers:
                continue
            market_time_str = item["regularMarketTime"]
            market_time = datetime.fromisoformat(market_time_str.replace("Z", "+00:00"))
            delay_minutes = (fetched_at - market_time).total_seconds() / 60.0

            quotes.append(
                Quote(
                    symbol=item["symbol"],
                    price=float(item["regularMarketPrice"]),
                    change=float(item["regularMarketChange"]),
                    change_pct=float(item["regularMarketChangePercent"]),
                    day_high=float(item["regularMarketDayHigh"]),
                    day_low=float(item["regularMarketDayLow"]),
                    previous_close=float(item["regularMarketPreviousClose"]),
                    volume=int(item["regularMarketVolume"]),
                    market_time=market_time,
                    fetched_at=fetched_at,
                    delay_minutes=max(0.0, delay_minutes),
                    currency=item.get("currency", "BRL"),
                )
            )
        return quotes


@pytest.mark.asyncio
async def test_ca01_fetch_quotes_returns_four_quotes(settings: Settings) -> None:
    """CA-01: fetch_quotes retorna exatamente 4 Quote com campos validos."""
    provider = MockBrapiProvider()
    quotes = await fetch_quotes(settings.tickers, settings, provider=provider)

    assert len(quotes) == 4, f"Esperado 4 quotes, recebido {len(quotes)}"

    for q in quotes:
        assert q.symbol in {"PETR4", "VALE3", "ITUB4", "MGLU3"}
        assert q.price > 0, f"{q.symbol}: price deve ser > 0, got {q.price}"
        assert isinstance(q.change_pct, float), f"{q.symbol}: change_pct deve ser float"
        assert q.market_time.tzinfo is not None, f"{q.symbol}: market_time deve ter tzinfo"
        assert q.fetched_at.tzinfo is not None, f"{q.symbol}: fetched_at deve ter tzinfo"


@pytest.mark.asyncio
async def test_ca01_quote_fields_types(settings: Settings) -> None:
    """CA-01: Verifica tipos exatos dos campos de Quote."""
    provider = MockBrapiProvider()
    quotes = await fetch_quotes(settings.tickers, settings, provider=provider)

    for q in quotes:
        assert isinstance(q.symbol, str)
        assert isinstance(q.price, float)
        assert isinstance(q.change, float)
        assert isinstance(q.change_pct, float)
        assert isinstance(q.day_high, float)
        assert isinstance(q.day_low, float)
        assert isinstance(q.previous_close, float)
        assert isinstance(q.volume, int)
        assert isinstance(q.market_time, datetime)
        assert isinstance(q.fetched_at, datetime)
        assert isinstance(q.delay_minutes, float)
        assert q.delay_minutes >= 0


@pytest.mark.asyncio
async def test_ca02_delay_calculated(settings: Settings) -> None:
    """CA-02: delay_minutes = (fetched_at - market_time).total_seconds() / 60."""
    provider = MockBrapiProvider()
    quotes = await fetch_quotes(settings.tickers, settings, provider=provider)

    for q in quotes:
        expected_delay = (q.fetched_at - q.market_time).total_seconds() / 60.0
        assert abs(q.delay_minutes - expected_delay) < 0.01, (
            f"{q.symbol}: delay_minutes esperado {expected_delay:.2f}, got {q.delay_minutes:.2f}"
        )


@pytest.mark.asyncio
async def test_ca02_delay_logged(settings: Settings, caplog) -> None:
    """CA-02: Log INFO deve conter 'delay=<N>min' para cada ticker."""
    provider = MockBrapiProvider()
    with caplog.at_level(logging.INFO, logger="acoes_b3_monitor.quote_collector"):
        quotes = await fetch_quotes(settings.tickers, settings, provider=provider)

    assert len(quotes) > 0
    # Verifica que ao menos um log com delay= existe para cada ticker
    for q in quotes:
        ticker_logs = [r.message for r in caplog.records if q.symbol in r.message]
        has_delay_log = any("delay=" in msg for msg in ticker_logs)
        assert has_delay_log, (
            f"Nenhum log com 'delay=' encontrado para {q.symbol}. "
            f"Logs disponiveis: {[r.message for r in caplog.records]}"
        )


@pytest.mark.asyncio
async def test_ca01_brapi_401_missing_token() -> None:
    """CA-01: BrapiProvider lanca ValueError em 401 MISSING_TOKEN."""
    import respx
    import httpx

    with respx.mock:
        respx.get("https://brapi.dev/api/quote/BBAS3").mock(
            return_value=httpx.Response(
                401,
                json={"error": True, "message": "Token de autenticacao nao fornecido", "code": "MISSING_TOKEN"},
            )
        )

        provider = BrapiProvider(token=None)
        with pytest.raises(ValueError, match="BRAPI_TOKEN ausente"):
            await provider.fetch_quotes(["BBAS3"])


@pytest.mark.asyncio
async def test_ca01_brapi_401_invalid_token() -> None:
    """CA-01: BrapiProvider lanca ValueError em 401 INVALID_TOKEN."""
    import respx
    import httpx

    with respx.mock:
        respx.get("https://brapi.dev/api/quote/PETR4").mock(
            return_value=httpx.Response(
                401,
                json={"error": True, "message": "Token invalido", "code": "INVALID_TOKEN"},
            )
        )

        provider = BrapiProvider(token="bad_token")
        with pytest.raises(ValueError, match="invalido ou expirado"):
            await provider.fetch_quotes(["PETR4"])
