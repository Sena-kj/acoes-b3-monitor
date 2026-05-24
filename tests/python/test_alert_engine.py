"""
Testes CA-03, CA-04, CA-05, CA-06 — alert_engine.

CA-03: Alerta price dispara (price <= trigger_value).
CA-04: Alerta pct dispara (price <= buy_price * (1 - pct/100)).
CA-05: Alerta nao dispara fora do gatilho.
CA-06: Deduplicacao: alerta suprimido se dentro do cooldown.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from acoes_b3_monitor.alert_engine import evaluate
from acoes_b3_monitor.storage import get_recent_alert, save_alert_event
from acoes_b3_monitor.types import AlertEvent, AlertRule, Quote, TriggerType


@pytest.mark.asyncio
async def test_ca03_price_trigger_fires(
    quote_petr4_below_trigger: Quote,
    rule_petr4_price: AlertRule,
    tmp_db: str,
) -> None:
    """CA-03: price=41.20 <= trigger_value=42.00 deve disparar AlertEvent."""
    events = await evaluate(
        quotes=[quote_petr4_below_trigger],
        rules=[rule_petr4_price],
        db_path=tmp_db,
        cooldown_minutes=60,
    )

    assert len(events) == 1
    event = events[0]
    assert event.ticker == "PETR4"
    assert event.trigger_fired is True
    assert event.trigger_type == TriggerType.PRICE
    assert event.price_at_trigger == pytest.approx(41.20, abs=0.01)


@pytest.mark.asyncio
async def test_ca04_pct_trigger_fires(
    quote_mglu3_below_trigger: Quote,
    rule_mglu3_pct: AlertRule,
    tmp_db: str,
) -> None:
    """CA-04: MGLU3 price=13.49 <= threshold=13.50 (pct=10, buy=15.00)."""
    events = await evaluate(
        quotes=[quote_mglu3_below_trigger],
        rules=[rule_mglu3_pct],
        db_path=tmp_db,
        cooldown_minutes=60,
    )

    assert len(events) == 1
    event = events[0]
    assert event.ticker == "MGLU3"
    assert event.trigger_fired is True
    assert event.trigger_type == TriggerType.PCT


@pytest.mark.asyncio
async def test_ca04_pct_threshold_boundary() -> None:
    """CA-04: price exatamente no threshold (=13.50) dispara."""
    from acoes_b3_monitor.alert_engine import _trigger_pct
    from tests.python.conftest import FAKE_FETCHED_AT, FAKE_MARKET_TIME, FAKE_DELAY

    quote = Quote(
        symbol="MGLU3",
        price=13.50,
        change=0, change_pct=0, day_high=14.0, day_low=13.0,
        previous_close=14.0, volume=1000,
        market_time=FAKE_MARKET_TIME, fetched_at=FAKE_FETCHED_AT,
        delay_minutes=FAKE_DELAY,
    )
    rule = AlertRule(ticker="MGLU3", trigger_type=TriggerType.PCT, trigger_value=10.0, buy_price=15.00)
    assert _trigger_pct(quote, rule) is True


@pytest.mark.asyncio
async def test_ca04_pct_above_threshold_no_fire() -> None:
    """CA-04: price acima do threshold (13.51) nao dispara."""
    from acoes_b3_monitor.alert_engine import _trigger_pct
    from tests.python.conftest import FAKE_FETCHED_AT, FAKE_MARKET_TIME, FAKE_DELAY

    quote = Quote(
        symbol="MGLU3",
        price=13.51,
        change=0, change_pct=0, day_high=14.0, day_low=13.0,
        previous_close=14.0, volume=1000,
        market_time=FAKE_MARKET_TIME, fetched_at=FAKE_FETCHED_AT,
        delay_minutes=FAKE_DELAY,
    )
    rule = AlertRule(ticker="MGLU3", trigger_type=TriggerType.PCT, trigger_value=10.0, buy_price=15.00)
    assert _trigger_pct(quote, rule) is False


@pytest.mark.asyncio
async def test_ca05_no_trigger_above_price(
    quote_vale3: Quote,
    rule_vale3_price_high: AlertRule,
    tmp_db: str,
) -> None:
    """CA-05: VALE3 price=62.10 > trigger_value=55.00 — lista vazia."""
    events = await evaluate(
        quotes=[quote_vale3],
        rules=[rule_vale3_price_high],
        db_path=tmp_db,
        cooldown_minutes=60,
    )
    assert events == []


@pytest.mark.asyncio
async def test_ca06_dedup_cooldown(
    quote_petr4_below_trigger: Quote,
    rule_petr4_price: AlertRule,
    tmp_db: str,
) -> None:
    """CA-06: Segundo evaluate dentro do cooldown nao emite novo AlertEvent."""
    # Primeiro disparo
    events1 = await evaluate(
        quotes=[quote_petr4_below_trigger],
        rules=[rule_petr4_price],
        db_path=tmp_db,
        cooldown_minutes=60,
    )
    assert len(events1) == 1

    # Segundo disparo — deve ser suprimido
    events2 = await evaluate(
        quotes=[quote_petr4_below_trigger],
        rules=[rule_petr4_price],
        db_path=tmp_db,
        cooldown_minutes=60,
    )
    assert events2 == [], "Alerta duplicado dentro do cooldown deve ser suprimido"


@pytest.mark.asyncio
async def test_ca06_dedup_expired_cooldown(
    quote_petr4_below_trigger: Quote,
    rule_petr4_price: AlertRule,
    tmp_db: str,
) -> None:
    """CA-06: Apos expirar o cooldown, novo alerta e emitido."""
    # Insere alerta com timestamp antigo (61 minutos atras)
    old_event = AlertEvent(
        ticker="PETR4",
        trigger_fired=True,
        trigger_type=TriggerType.PRICE,
        trigger_value=42.00,
        price_at_trigger=41.20,
        buy_price=45.00,
        pct_from_buy=-8.44,
        fired_at=datetime.now(tz=timezone.utc) - timedelta(minutes=61),
    )
    await save_alert_event(old_event, tmp_db)

    # Cooldown de 60min: evento de 61min atras nao deve bloquear
    events = await evaluate(
        quotes=[quote_petr4_below_trigger],
        rules=[rule_petr4_price],
        db_path=tmp_db,
        cooldown_minutes=60,
    )
    assert len(events) == 1, "Apos expirar cooldown, deve disparar novo alerta"


@pytest.mark.asyncio
async def test_ca05_no_alert_for_missing_ticker(
    quote_petr4: Quote,
    tmp_db: str,
) -> None:
    """CA-05: Regra para ticker sem cotacao nao gera alerta."""
    rule_outro = AlertRule(
        ticker="AAPL3",
        trigger_type=TriggerType.PRICE,
        trigger_value=100.0,
        buy_price=None,
    )
    events = await evaluate(
        quotes=[quote_petr4],
        rules=[rule_outro],
        db_path=tmp_db,
        cooldown_minutes=60,
    )
    assert events == []
