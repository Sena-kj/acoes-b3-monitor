"""
quote_collector.py — Fetch de cotacoes via provider abstrato (BrapiProvider no MVP).

Funcao principal:
  fetch_quotes(tickers, settings) -> list[Quote]

Protocol QuoteProvider:
  async def fetch_quotes(self, tickers: list[str]) -> list[Quote]

Implementacoes concretas em providers/.
"""

from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

import httpx

from .types import Quote, Settings

logger = logging.getLogger(__name__)

BRAPI_BASE_URL = "https://brapi.dev/api"
DEFAULT_USER_AGENT = "Mozilla/5.0 (compatible; acoes-b3-monitor/1.0)"


@runtime_checkable
class QuoteProvider(Protocol):
    async def fetch_quotes(self, tickers: list[str]) -> list[Quote]:
        ...


class BrapiProvider:
    """
    Provider de cotacao usando brapi.dev.

    Free: somente PETR4/VALE3/ITUB4/MGLU3 sem token (allowlist).
    Pago: qualquer ticker com token via query param ?token=.
    """

    def __init__(self, token: str | None = None) -> None:
        self._token = token

    async def fetch_quotes(self, tickers: list[str]) -> list[Quote]:
        """Busca cotacoes de todos os tickers em um unico GET (economiza quota)."""
        if not tickers:
            return []

        tickers_str = ",".join(tickers)
        url = f"{BRAPI_BASE_URL}/quote/{tickers_str}"
        params: dict[str, str] = {}
        if self._token:
            params["token"] = self._token

        async with httpx.AsyncClient(
            headers={"User-Agent": DEFAULT_USER_AGENT},
            timeout=15.0,
        ) as client:
            resp = await client.get(url, params=params)

        if resp.status_code == 401:
            data = resp.json()
            code = data.get("code", "UNKNOWN")
            if code == "MISSING_TOKEN":
                raise ValueError(
                    "brapi: BRAPI_TOKEN ausente. Free suporta apenas PETR4/VALE3/ITUB4/MGLU3. "
                    "Defina BRAPI_TOKEN para outros tickers."
                )
            elif code == "INVALID_TOKEN":
                raise ValueError("brapi: BRAPI_TOKEN invalido ou expirado. Verifique a variavel de ambiente.")
            else:
                raise ValueError(f"brapi: erro de autenticacao inesperado: {data}")

        resp.raise_for_status()
        data = resp.json()

        from datetime import datetime, timezone

        fetched_at_str = data.get("requestedAt", "")
        try:
            fetched_at = datetime.fromisoformat(fetched_at_str.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            fetched_at = datetime.now(tz=timezone.utc)

        quotes: list[Quote] = []
        for item in data.get("results", []):
            market_time_str = item.get("regularMarketTime", "")
            try:
                market_time = datetime.fromisoformat(market_time_str.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                market_time = fetched_at

            delay_minutes = (fetched_at - market_time).total_seconds() / 60.0

            q = Quote(
                symbol=item["symbol"],
                price=float(item.get("regularMarketPrice", 0)),
                change=float(item.get("regularMarketChange", 0)),
                change_pct=float(item.get("regularMarketChangePercent", 0)),
                day_high=float(item.get("regularMarketDayHigh", 0)),
                day_low=float(item.get("regularMarketDayLow", 0)),
                previous_close=float(item.get("regularMarketPreviousClose", 0)),
                volume=int(item.get("regularMarketVolume", 0)),
                market_time=market_time,
                fetched_at=fetched_at,
                delay_minutes=max(0.0, delay_minutes),
                currency=item.get("currency", "BRL"),
            )
            # Log removido daqui — a facade fetch_quotes ja loga delay por ticker (CODE-H2)
            quotes.append(q)

        return quotes


async def fetch_quotes(
    tickers: list[str],
    settings: Settings,
    provider: QuoteProvider | None = None,
) -> list[Quote]:
    """
    Funcao de fachada. Usa BrapiProvider por default.
    Aceita provider externo para facilitar testes.
    Loga delay=Nmin para cada ticker (CA-02).
    """
    if provider is None:
        provider = BrapiProvider(token=settings.brapi_token)

    quotes = await provider.fetch_quotes(tickers)

    # CA-02: garante que delay e logado aqui, independente do provider
    for q in quotes:
        logger.info(
            "fetch_quotes %s: R$ %.2f (%.2f%%) delay=%.1fmin",
            q.symbol,
            q.price,
            q.change_pct,
            q.delay_minutes,
        )

    return quotes
