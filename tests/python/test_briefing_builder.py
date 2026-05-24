"""
Testes CA-10 — briefing_builder.

CA-10: build() retorna DailyBriefing com quotes[], news_by_ticker, summary.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from acoes_b3_monitor.briefing_builder import build
from acoes_b3_monitor.types import DailyBriefing, NewsAnalysis, Quote


@pytest.mark.asyncio
async def test_ca10_briefing_has_all_tickers(
    quote_petr4: Quote,
    quote_vale3: Quote,
    news_analysis_vale3: NewsAnalysis,
    settings,
) -> None:
    """CA-10: DailyBriefing.quotes contem todos os tickers configurados."""
    quotes = [quote_petr4, quote_vale3]
    news_by_ticker = {
        "PETR4": [],
        "VALE3": [news_analysis_vale3],
        "ITUB4": [],
        "MGLU3": [],
    }

    briefing = await build(quotes, news_by_ticker, settings, generate_summary=False)

    assert isinstance(briefing, DailyBriefing)
    symbols = [q.symbol for q in briefing.quotes]
    assert "PETR4" in symbols
    assert "VALE3" in symbols


@pytest.mark.asyncio
async def test_ca10_briefing_news_by_ticker(
    quote_vale3: Quote,
    news_analysis_vale3: NewsAnalysis,
    settings,
) -> None:
    """CA-10: news_by_ticker[ticker] contem NewsAnalysis das ultimas 24h."""
    news_by_ticker = {"VALE3": [news_analysis_vale3]}

    briefing = await build([quote_vale3], news_by_ticker, settings, generate_summary=False)

    assert "VALE3" in briefing.news_by_ticker
    assert len(briefing.news_by_ticker["VALE3"]) == 1
    assert briefing.news_by_ticker["VALE3"][0].news_guid == news_analysis_vale3.news_guid


@pytest.mark.asyncio
async def test_ca10_briefing_generated_at_utc(
    quote_petr4: Quote,
    settings,
) -> None:
    """CA-10: generated_at deve ser timezone-aware UTC."""
    briefing = await build([quote_petr4], {}, settings, generate_summary=False)

    assert briefing.generated_at.tzinfo is not None
    assert isinstance(briefing.generated_at, datetime)


@pytest.mark.asyncio
async def test_ca10_briefing_date_format(
    quote_petr4: Quote,
    settings,
) -> None:
    """CA-10: briefing_date deve estar no formato YYYY-MM-DD."""
    import re
    briefing = await build([quote_petr4], {}, settings, generate_summary=False)

    assert re.match(r"^\d{4}-\d{2}-\d{2}$", briefing.briefing_date), (
        f"briefing_date mal formatado: {briefing.briefing_date!r}"
    )


@pytest.mark.asyncio
async def test_ca10_briefing_summary_with_mock(
    quote_vale3: Quote,
    news_analysis_vale3: NewsAnalysis,
    settings,
) -> None:
    """CA-10: summary e gerado pelo Claude (mockado aqui)."""
    from unittest.mock import MagicMock, patch

    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="Mercado volatil. VALE3 reportou incidente operacional. Carteira em cautela.")]
    mock_response.usage = MagicMock(input_tokens=100, output_tokens=30)

    with patch("acoes_b3_monitor.briefing_builder.anthropic.Anthropic") as mock_cls:
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response
        mock_cls.return_value = mock_client

        briefing = await build(
            [quote_vale3],
            {"VALE3": [news_analysis_vale3]},
            settings,
            generate_summary=True,
        )

    assert isinstance(briefing.summary, str)
    assert len(briefing.summary.strip()) > 0


@pytest.mark.asyncio
async def test_ca10_briefing_empty_news(
    quote_petr4: Quote,
    quote_vale3: Quote,
    settings,
) -> None:
    """CA-10: Briefing com news_by_ticker vazio deve funcionar sem erro."""
    briefing = await build(
        [quote_petr4, quote_vale3],
        {"PETR4": [], "VALE3": []},
        settings,
        generate_summary=False,
    )
    assert briefing.news_by_ticker["PETR4"] == []
    assert briefing.news_by_ticker["VALE3"] == []
