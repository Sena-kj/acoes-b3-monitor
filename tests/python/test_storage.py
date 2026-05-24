"""
Testes de storage.py — init_db, save/get de todos os tipos.
Cobre deduplicacao (CA-08 parte de storage) e cooldown (CA-06 parte de storage).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from acoes_b3_monitor.storage import (
    get_news_analyses_since,
    get_news_since,
    get_recent_alert,
    init_db,
    is_cvm_protocol_seen,
    is_news_item_seen,
    mark_cvm_protocol_seen,
    save_alert_event,
    save_news_analysis,
    save_news_item,
    save_quote,
)
from acoes_b3_monitor.types import AlertEvent, NewsAnalysis, NewsItem, Sentiment, TriggerType


@pytest.mark.asyncio
async def test_init_db_creates_tables(tmp_path) -> None:
    """init_db cria todas as tabelas sem erro."""
    db_path = str(tmp_path / "test.db")
    await init_db(db_path)
    await init_db(db_path)  # idempotente


@pytest.mark.asyncio
async def test_save_and_get_quote(quote_petr4, tmp_db) -> None:
    """save_quote persiste e nao levanta excecao."""
    await save_quote(quote_petr4, tmp_db)


@pytest.mark.asyncio
async def test_save_news_item_dedup(news_item_vale3, tmp_db) -> None:
    """Segundo save do mesmo item e silenciosamente ignorado."""
    await save_news_item(news_item_vale3, tmp_db)
    await save_news_item(news_item_vale3, tmp_db)  # nao deve lancar

    assert await is_news_item_seen(news_item_vale3.guid, tmp_db) is True


@pytest.mark.asyncio
async def test_is_news_item_seen_false_for_new(tmp_db) -> None:
    """is_news_item_seen retorna False para guid desconhecido."""
    assert await is_news_item_seen("guid:nao:existe", tmp_db) is False


@pytest.mark.asyncio
async def test_get_news_since_filters_by_ticker(news_item_vale3, tmp_db) -> None:
    """get_news_since retorna apenas itens do ticker solicitado."""
    await save_news_item(news_item_vale3, tmp_db)

    since = datetime(2026, 1, 1, tzinfo=timezone.utc)
    items = await get_news_since("VALE3", since, tmp_db)
    assert len(items) >= 1
    assert all("VALE3" in i.tickers for i in items)

    # Nao deve retornar para outro ticker
    items_petr4 = await get_news_since("PETR4", since, tmp_db)
    assert all("PETR4" in i.tickers for i in items_petr4)


@pytest.mark.asyncio
async def test_get_recent_alert_returns_none_when_empty(tmp_db) -> None:
    """get_recent_alert retorna None quando nao ha alertas recentes."""
    result = await get_recent_alert("PETR4", 60, tmp_db)
    assert result is None


@pytest.mark.asyncio
async def test_get_recent_alert_within_window(tmp_db) -> None:
    """get_recent_alert retorna AlertEvent dentro da janela de cooldown."""
    event = AlertEvent(
        ticker="PETR4",
        trigger_fired=True,
        trigger_type=TriggerType.PRICE,
        trigger_value=42.00,
        price_at_trigger=41.20,
        buy_price=45.00,
        pct_from_buy=-8.44,
        fired_at=datetime.now(tz=timezone.utc),
    )
    await save_alert_event(event, tmp_db)

    recent = await get_recent_alert("PETR4", 60, tmp_db)
    assert recent is not None
    assert recent.ticker == "PETR4"


@pytest.mark.asyncio
async def test_get_recent_alert_outside_window(tmp_db) -> None:
    """get_recent_alert retorna None para alerta antigo (fora do cooldown)."""
    event = AlertEvent(
        ticker="PETR4",
        trigger_fired=True,
        trigger_type=TriggerType.PRICE,
        trigger_value=42.00,
        price_at_trigger=41.20,
        buy_price=45.00,
        pct_from_buy=-8.44,
        fired_at=datetime.now(tz=timezone.utc) - timedelta(minutes=65),
    )
    await save_alert_event(event, tmp_db)

    # Janela de 60min: alerta de 65min atras nao deve ser retornado
    recent = await get_recent_alert("PETR4", 60, tmp_db)
    assert recent is None


@pytest.mark.asyncio
async def test_save_and_get_news_analysis(news_analysis_vale3, tmp_db) -> None:
    """save_news_analysis persiste e get_news_analyses_since retorna corretamente."""
    await save_news_analysis(news_analysis_vale3, tmp_db)

    since = datetime(2026, 1, 1, tzinfo=timezone.utc)
    analyses = await get_news_analyses_since("VALE3", since, tmp_db)

    assert len(analyses) >= 1
    found = next((a for a in analyses if a.news_guid == news_analysis_vale3.news_guid), None)
    assert found is not None
    assert found.sentiment == Sentiment.NEGATIVO


@pytest.mark.asyncio
async def test_cvm_protocol_dedup(tmp_db) -> None:
    """mark_cvm_protocol_seen retorna True no primeiro, False no segundo."""
    protocolo = "001023IPE20260524001"

    is_new = await mark_cvm_protocol_seen(protocolo, tmp_db)
    assert is_new is True

    is_new_again = await mark_cvm_protocol_seen(protocolo, tmp_db)
    assert is_new_again is False

    assert await is_cvm_protocol_seen(protocolo, tmp_db) is True
