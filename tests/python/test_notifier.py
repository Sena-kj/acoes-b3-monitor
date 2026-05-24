"""
Testes CA-11 — notifier.

CA-11: send_message() faz POST para Telegram e retorna sem excecao.
"""

from __future__ import annotations

import pytest
import respx
import httpx

from acoes_b3_monitor.notifier import send_alert, send_briefing, send_message, send_news_analysis
from acoes_b3_monitor.types import (
    AlertEvent,
    DailyBriefing,
    NewsAnalysis,
    NewsItem,
    NewsSource,
    Quote,
    Sentiment,
    TriggerType,
)
from datetime import datetime, timezone


TELEGRAM_SUCCESS = {"ok": True, "result": {"message_id": 42}}


@pytest.mark.asyncio
async def test_ca11_send_message_success(settings) -> None:
    """CA-11: send_message faz POST correto e nao levanta excecao."""
    with respx.mock:
        respx.post(
            f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
        ).mock(return_value=httpx.Response(200, json=TELEGRAM_SUCCESS))

        await send_message("Teste de mensagem", settings)


@pytest.mark.asyncio
async def test_ca11_send_message_payload(settings) -> None:
    """CA-11: Payload enviado ao Telegram contem chat_id, text e parse_mode."""
    sent_payload = {}

    async def capture(request):
        import json as _json
        sent_payload.update(_json.loads(request.content))
        return httpx.Response(200, json=TELEGRAM_SUCCESS)

    with respx.mock:
        respx.post(
            f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
        ).mock(side_effect=capture)

        await send_message("<b>Alerta!</b>", settings)

    assert sent_payload["chat_id"] == settings.telegram_chat_id
    assert sent_payload["text"] == "<b>Alerta!</b>"
    assert sent_payload["parse_mode"] == "HTML"


@pytest.mark.asyncio
async def test_ca11_send_message_truncates_long_text(settings) -> None:
    """CA-11: Mensagem maior que 4096 chars deve ser truncada."""
    long_text = "x" * 5000

    with respx.mock:
        route = respx.post(
            f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
        ).mock(return_value=httpx.Response(200, json=TELEGRAM_SUCCESS))

        await send_message(long_text, settings)

    import json as _json
    request = route.calls.last.request
    body = _json.loads(request.content)
    assert len(body["text"]) <= 4096, f"Texto nao truncado: {len(body['text'])} chars"


@pytest.mark.asyncio
async def test_ca11_send_message_retry_on_429(settings) -> None:
    """CA-11: Retry automatico em 429 (Too Many Requests)."""
    call_count = 0

    async def rate_limit_then_ok(request):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(429, json={"ok": False, "parameters": {"retry_after": 0}})
        return httpx.Response(200, json=TELEGRAM_SUCCESS)

    with respx.mock:
        respx.post(
            f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
        ).mock(side_effect=rate_limit_then_ok)

        await send_message("Teste retry", settings)

    assert call_count == 2, f"Esperado 2 tentativas, fez {call_count}"


@pytest.mark.asyncio
async def test_ca11_send_alert_formats_message(
    quote_petr4_below_trigger: Quote,
    settings,
) -> None:
    """CA-11: send_alert formata mensagem de alerta e envia."""
    from tests.python.conftest import FAKE_FETCHED_AT, FAKE_MARKET_TIME, FAKE_DELAY

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

    sent_text = []

    async def capture(request):
        import json as _json
        body = _json.loads(request.content)
        sent_text.append(body["text"])
        return httpx.Response(200, json=TELEGRAM_SUCCESS)

    with respx.mock:
        respx.post(
            f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
        ).mock(side_effect=capture)

        await send_alert(event, quote_petr4_below_trigger, settings)

    assert len(sent_text) == 1
    msg = sent_text[0]
    assert "PETR4" in msg
    assert "41,20" in msg or "41.20" in msg


@pytest.mark.asyncio
async def test_ca11_send_message_400_raises(settings) -> None:
    """CA-11: 400 Bad Request deve levantar RuntimeError."""
    with respx.mock:
        respx.post(
            f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
        ).mock(
            return_value=httpx.Response(
                400,
                json={"ok": False, "error_code": 400, "description": "Bad Request: chat not found"},
            )
        )

        with pytest.raises(RuntimeError, match="bad request"):
            await send_message("Teste erro", settings)
