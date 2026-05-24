"""
scheduler.py — Agendamento de jobs com APScheduler 3.x (AsyncIOScheduler).

Jobs:
  - quote_poll_job: cotacoes a cada 5min, seg-sex 09:45-17:30 BRT
  - news_fetch_job: noticias a cada 30min, sempre
  - briefing_job: briefing diario no horario configurado (BRT)
  - cvm_download_job: download CVM IPE 1x/dia as 06:00 BRT

Funcao principal:
  create_scheduler(settings, db_path) -> AsyncIOScheduler

Padrão: apscheduler-fastapi-lifespan (vault).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from .config import get_db_path
from .types import Settings

logger = logging.getLogger(__name__)

BRT = pytz.timezone("America/Sao_Paulo")


def _make_quote_poll_job(settings: Settings, db_path: str):
    """Closure que captura settings e db_path para o job de cotacao."""
    from .alert_engine import evaluate
    from .notifier import send_alert
    from .quote_collector import fetch_quotes
    from .storage import init_db, save_quote

    async def job() -> None:
        """Coleta cotacoes e avalia alertas (seg-sex 09:45-17:30 BRT)."""
        now_brt = datetime.now(tz=timezone.utc).astimezone(BRT)

        # Verifica dia da semana (0=seg, 4=sex)
        if now_brt.weekday() > 4:
            logger.debug("quote_poll_job: final de semana, pulando")
            return

        # Verifica horario de pregao
        market_open_h, market_open_m = map(int, settings.market_open.split(":"))
        market_close_h, market_close_m = map(int, settings.market_close.split(":"))
        now_minutes = now_brt.hour * 60 + now_brt.minute
        open_minutes = market_open_h * 60 + market_open_m
        close_minutes = market_close_h * 60 + market_close_m

        if not (open_minutes <= now_minutes <= close_minutes):
            logger.debug("quote_poll_job: fora do pregao (%s), pulando", now_brt.strftime("%H:%M"))
            return

        try:
            await init_db(db_path)
            quotes = await fetch_quotes(settings.tickers, settings)
            rules = [cfg.alert_rule for cfg in settings.ticker_configs.values()]

            for q in quotes:
                await save_quote(q, db_path)

            events = await evaluate(quotes, rules, db_path, settings.alert_cooldown_minutes)

            for event in events:
                quote = next((q for q in quotes if q.symbol == event.ticker), None)
                if quote:
                    await send_alert(event, quote, settings)
        except Exception as e:
            logger.error("quote_poll_job: erro: %s", e, exc_info=True)

    return job


def _make_news_fetch_job(settings: Settings, db_path: str):
    """Closure para o job de coleta de noticias."""
    from .news_analyzer import analyze
    from .news_collector import fetch_news
    from .notifier import send_news_analysis
    from .storage import init_db, is_news_item_seen, save_news_analysis, save_news_item

    async def job() -> None:
        """Coleta noticias, analisa com Claude e notifica via Telegram."""
        try:
            await init_db(db_path)
            items = await fetch_news(settings.tickers, settings, db_path)

            for item in items:
                # Dedup: verifica se ja foi persistido
                if await is_news_item_seen(item.guid, db_path):
                    continue

                await save_news_item(item, db_path)

                # Analisa com Claude e notifica
                try:
                    analysis = await analyze(item, settings)
                    await save_news_analysis(analysis, db_path)
                    await send_news_analysis(analysis, item, settings)
                except Exception as e:
                    logger.error("news_fetch_job: erro ao analisar %s: %s", item.guid, e)
        except Exception as e:
            logger.error("news_fetch_job: erro geral: %s", e, exc_info=True)

    return job


def _make_briefing_job(settings: Settings, db_path: str):
    """Closure para o job de briefing diario."""
    from datetime import timedelta

    from .briefing_builder import build
    from .notifier import send_briefing
    from .quote_collector import fetch_quotes
    from .storage import get_news_analyses_since, init_db

    async def job() -> None:
        """Gera e envia briefing diario."""
        try:
            await init_db(db_path)
            quotes = await fetch_quotes(settings.tickers, settings)

            since_dt = datetime.now(tz=timezone.utc) - timedelta(hours=24)
            news_by_ticker = {}
            for ticker in settings.tickers:
                analyses = await get_news_analyses_since(ticker, since_dt, db_path)
                news_by_ticker[ticker] = analyses

            briefing = await build(quotes, news_by_ticker, settings)
            await send_briefing(briefing, settings)
        except Exception as e:
            logger.error("briefing_job: erro: %s", e, exc_info=True)

    return job


def _make_cvm_download_job(settings: Settings, db_path: str):
    """Closure para o job de download do CVM IPE."""
    import httpx

    from .news_collector import fetch_cvm_ipe
    from .news_analyzer import analyze
    from .notifier import send_news_analysis
    from .storage import init_db, is_news_item_seen, save_news_analysis, save_news_item

    async def job() -> None:
        """Baixa CVM IPE, processa fatos relevantes novos."""
        try:
            await init_db(db_path)
            async with httpx.AsyncClient(
                headers={"User-Agent": "Mozilla/5.0 (compatible; acoes-b3-monitor/1.0)"},
                timeout=60.0,
            ) as client:
                items = await fetch_cvm_ipe(settings.tickers, db_path, client)

            for item in items:
                if await is_news_item_seen(item.guid, db_path):
                    continue
                await save_news_item(item, db_path)
                try:
                    analysis = await analyze(item, settings)
                    await save_news_analysis(analysis, db_path)
                    await send_news_analysis(analysis, item, settings)
                except Exception as e:
                    logger.error("cvm_download_job: erro ao analisar %s: %s", item.guid, e)
        except Exception as e:
            logger.error("cvm_download_job: erro geral: %s", e, exc_info=True)

    return job


def create_scheduler(
    settings: Settings | None = None,
    db_path: str | None = None,
) -> AsyncIOScheduler:
    """
    Cria e configura AsyncIOScheduler com todos os jobs.

    Nao chama scheduler.start() — chamado em main.py.
    Aceita settings e db_path para facilitar testes (injecao de dependencias).
    """
    from .config import get_settings, get_db_path as _get_db_path

    if settings is None:
        settings = get_settings()
    if db_path is None:
        db_path = _get_db_path()

    scheduler = AsyncIOScheduler(timezone=BRT)

    # Job 1: polling de cotacao — a cada N min (filtro de pregao dentro do job)
    scheduler.add_job(
        _make_quote_poll_job(settings, db_path),
        IntervalTrigger(minutes=settings.quote_poll_interval_minutes, timezone=BRT),
        id="quote_poll",
        replace_existing=True,
        misfire_grace_time=60,
    )

    # Job 2: coleta de noticias — a cada 30min, sempre
    scheduler.add_job(
        _make_news_fetch_job(settings, db_path),
        IntervalTrigger(minutes=settings.news_fetch_interval_minutes, timezone=BRT),
        id="news_fetch",
        replace_existing=True,
        misfire_grace_time=120,
    )

    # Job 3: briefing diario — horario configurado em BRT (HH:MM)
    briefing_h, briefing_m = map(int, settings.briefing_time.split(":"))
    scheduler.add_job(
        _make_briefing_job(settings, db_path),
        CronTrigger(hour=briefing_h, minute=briefing_m, timezone=BRT),
        id="briefing",
        replace_existing=True,
        misfire_grace_time=600,
    )

    # Job 4: download CVM IPE — 1x/dia as 06:00 BRT
    scheduler.add_job(
        _make_cvm_download_job(settings, db_path),
        CronTrigger(hour=6, minute=0, timezone=BRT),
        id="cvm_download",
        replace_existing=True,
        misfire_grace_time=300,
    )

    logger.info(
        "Scheduler configurado: %d jobs (quote_poll=%dmin, news=%dmin, briefing=%s BRT, cvm=06:00 BRT)",
        len(scheduler.get_jobs()),
        settings.quote_poll_interval_minutes,
        settings.news_fetch_interval_minutes,
        settings.briefing_time,
    )

    return scheduler
