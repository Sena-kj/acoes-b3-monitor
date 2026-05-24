"""
alert_engine.py — Avalia Quote[] contra AlertRule[] e emite AlertEvent[].

Funcao principal:
  evaluate(quotes, rules, db_path, cooldown_minutes) -> list[AlertEvent]

Deduplicacao: se AlertEvent para o mesmo ticker existir no storage
dentro da janela de cooldown (default 60min), nao emite novo evento.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from .storage import get_recent_alert, save_alert_event
from .types import AlertEvent, AlertRule, Quote, TriggerType

logger = logging.getLogger(__name__)


def _trigger_price(quote: Quote, rule: AlertRule) -> bool:
    """CA-03: dispara quando price <= trigger_value (R$ absoluto)."""
    return quote.price <= rule.trigger_value


def _trigger_pct(quote: Quote, rule: AlertRule) -> bool:
    """
    CA-04: dispara quando price <= buy_price * (1 - trigger_value/100).
    Ex: buy_price=15.00, trigger_value=10 -> gatilho em 13.50.
    """
    if rule.buy_price is None:
        logger.warning("AlertRule PCT para %s sem buy_price; pulando.", rule.ticker)
        return False
    threshold = rule.buy_price * (1.0 - rule.trigger_value / 100.0)
    return quote.price <= threshold


def _compute_pct_from_buy(price: float, buy_price: float | None) -> float | None:
    if buy_price is None or buy_price == 0:
        return None
    return (price - buy_price) / buy_price * 100.0


async def evaluate(
    quotes: list[Quote],
    rules: list[AlertRule],
    db_path: str,
    cooldown_minutes: int = 60,
) -> list[AlertEvent]:
    """
    Avalia cada Quote contra sua AlertRule correspondente.

    CA-05: Nao emite evento se preco nao cruza o gatilho.
    CA-06: Nao emite evento se ja disparou dentro da janela de cooldown.

    Retorna lista de AlertEvent (pode ser vazia).
    """
    # Indexa quotes por symbol para O(1) lookup
    quote_map: dict[str, Quote] = {q.symbol: q for q in quotes}
    events: list[AlertEvent] = []

    for rule in rules:
        quote = quote_map.get(rule.ticker)
        if quote is None:
            logger.debug("Sem cotacao para ticker %s; pulando avaliacao de alerta.", rule.ticker)
            continue

        # Verifica se o gatilho dispara
        match rule.trigger_type:
            case TriggerType.PRICE:
                fired = _trigger_price(quote, rule)
            case TriggerType.PCT:
                fired = _trigger_pct(quote, rule)
            case _:
                logger.warning("TriggerType desconhecido %s; pulando.", rule.trigger_type)
                continue

        if not fired:
            logger.debug(
                "Alerta %s nao disparado: preco=%.2f trigger_type=%s trigger_value=%.2f",
                rule.ticker, quote.price, rule.trigger_type.value, rule.trigger_value,
            )
            continue

        # Deduplicacao: verifica cooldown no storage
        recent = await get_recent_alert(rule.ticker, cooldown_minutes, db_path)
        if recent is not None:
            logger.info(
                "Alerta %s suprimido: ja disparado em %s (cooldown %dmin)",
                rule.ticker, recent.fired_at.isoformat(), cooldown_minutes,
            )
            continue

        pct_from_buy = _compute_pct_from_buy(quote.price, rule.buy_price)

        event = AlertEvent(
            ticker=rule.ticker,
            trigger_fired=True,
            trigger_type=rule.trigger_type,
            trigger_value=rule.trigger_value,
            price_at_trigger=quote.price,
            buy_price=rule.buy_price,
            pct_from_buy=pct_from_buy,
            fired_at=datetime.now(tz=timezone.utc),
        )

        await save_alert_event(event, db_path)
        logger.info(
            "Alerta disparado: %s preco=%.2f trigger_type=%s trigger_value=%.2f",
            event.ticker, event.price_at_trigger, event.trigger_type.value, event.trigger_value,
        )
        events.append(event)

    return events
