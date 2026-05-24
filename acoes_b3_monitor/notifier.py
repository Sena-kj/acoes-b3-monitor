"""
notifier.py — Envio de mensagens via Telegram Bot API.

Funcoes principais (contrato do api-contract.yaml):
  send_message(text, settings) -> None
  send_alert(event, quote, settings) -> None
  send_news_analysis(analysis, item, settings) -> None
  send_briefing(briefing, settings) -> None

Detalhes:
- parse_mode=HTML
- Trunca para 4096 chars (limite Telegram)
- Retry em 429 com retry_after
- POST para https://api.telegram.org/bot{TOKEN}/sendMessage
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timezone

import httpx
import pytz

from .types import AlertEvent, DailyBriefing, NewsAnalysis, NewsItem, Quote, Settings, TriggerType

logger = logging.getLogger(__name__)

TELEGRAM_API_BASE = "https://api.telegram.org"
MAX_MESSAGE_LENGTH = 4096
BRT = pytz.timezone("America/Sao_Paulo")


def _truncate(text: str, max_len: int = MAX_MESSAGE_LENGTH) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def _fmt_brt(dt_utc) -> str:
    """Formata datetime UTC para BRT legivel."""
    if dt_utc is None:
        return "N/A"
    try:
        brt_dt = dt_utc.astimezone(BRT)
        return brt_dt.strftime("%d/%m/%Y %H:%M BRT")
    except Exception:
        return str(dt_utc)


def _format_price_alert(event: AlertEvent, quote: Quote) -> str:
    """Formata mensagem de alerta de preco (spec: Fluxo de UX)."""
    lines = [f"<b>[ALERTA {event.ticker}]</b> Preco atual: R$ {event.price_at_trigger:.2f}"]

    if event.trigger_type == TriggerType.PRICE:
        trigger_desc = f"R$ {event.trigger_value:.2f}"
    else:
        trigger_desc = f"{event.trigger_value:.1f}% abaixo do preco de compra"

    buy_part = ""
    if event.buy_price is not None and event.pct_from_buy is not None:
        buy_part = f" (preco de compra R$ {event.buy_price:.2f} {event.pct_from_buy:+.1f}%)"

    lines.append(f"Gatilho atingido: {trigger_desc}{buy_part}")
    lines.append(f"Cotacao com delay ~15min (brapi free). Horario do dado: {_fmt_brt(quote.market_time)}")
    return "\n".join(lines)


def _format_news_analysis(analysis: NewsAnalysis, item: NewsItem) -> str:
    """Formata mensagem de analise de noticia (spec: Fluxo de UX)."""
    ticker = analysis.ticker
    source_label = item.source.value.replace("_", " ").title()
    pub_str = _fmt_brt(item.published_at)

    lines = [
        f"<b>[NOTICIA {ticker}]</b> {source_label} — {pub_str}",
        f'"{item.title}"',
        f"Fonte: {source_label} | Link: {item.url}",
        "",
        "Analise Claude:",
        f"Sentimento: {analysis.sentiment.value}",
        f"Contexto: {analysis.summary}",
    ]
    return "\n".join(lines)


def _format_briefing(briefing: DailyBriefing, tickers: list[str]) -> str:
    """Formata briefing diario (spec: Fluxo de UX)."""
    from datetime import date

    lines = [f"<b>Bom dia! Carteira B3 — {briefing.briefing_date}</b>", ""]

    for q in briefing.quotes:
        configs_buy = None
        # Nao temos acesso a settings aqui — apenas exibimos dados disponíveis no Quote
        sign = "+" if q.change_pct >= 0 else ""
        line = f"<b>{q.symbol}</b>  R$ {q.price:.2f}  {sign}{q.change_pct:.2f}% hoje"
        lines.append(line)

    lines.append("")
    lines.append("Noticias das ultimas 24h:")

    for ticker in tickers:
        analyses = briefing.news_by_ticker.get(ticker, [])
        if not analyses:
            lines.append(f"• {ticker}: sem noticias")
        else:
            # Sentimento medio
            sentiment_counts: dict[str, int] = {}
            for a in analyses:
                sentiment_counts[a.sentiment.value] = sentiment_counts.get(a.sentiment.value, 0) + 1
            dominant = max(sentiment_counts, key=lambda k: sentiment_counts[k])

            if len(analyses) == 1:
                lines.append(f"• {ticker}: 1 noticia — sentimento: {dominant}")
            else:
                lines.append(f"• {ticker}: {len(analyses)} noticias — sentimento medio: {dominant}")

    if briefing.summary:
        lines.append("")
        lines.append(briefing.summary)

    return "\n".join(lines)


async def send_message(text: str, settings: Settings) -> None:
    """
    Envia mensagem de texto para o Telegram.
    Retry automatico em 429. Trunca em 4096 chars.
    """
    url = f"{TELEGRAM_API_BASE}/bot{settings.telegram_bot_token}/sendMessage"
    payload = {
        "chat_id": settings.telegram_chat_id,
        "text": _truncate(text),
        "parse_mode": "HTML",
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        for attempt in range(3):
            resp = await client.post(url, json=payload)

            if resp.status_code == 429:
                retry_after = resp.json().get("parameters", {}).get("retry_after", 5)
                logger.warning("Telegram 429: aguardando %ds antes de retry", retry_after)
                await asyncio.sleep(retry_after)
                continue

            if resp.status_code == 400:
                data = resp.json()
                # Nao loga payload — o token Telegram esta na URL/body e pode vazar em logs
                logger.error("Telegram 400: %s", data)
                raise RuntimeError(f"Telegram bad request: {data.get('description', 'unknown')}")

            resp.raise_for_status()
            logger.debug("Telegram mensagem enviada: status=%d", resp.status_code)
            return

    raise RuntimeError("Telegram: excedido numero de tentativas de envio")


async def send_alert(event: AlertEvent, quote: Quote, settings: Settings) -> None:
    """Envia alerta de preco formatado."""
    text = _format_price_alert(event, quote)
    await send_message(text, settings)


async def send_news_analysis(
    analysis: NewsAnalysis,
    item: NewsItem,
    settings: Settings,
) -> None:
    """Envia analise de noticia formatada."""
    text = _format_news_analysis(analysis, item)
    await send_message(text, settings)


async def send_briefing(briefing: DailyBriefing, settings: Settings) -> None:
    """Envia briefing diario formatado."""
    tickers = [q.symbol for q in briefing.quotes]
    text = _format_briefing(briefing, tickers)
    await send_message(text, settings)
