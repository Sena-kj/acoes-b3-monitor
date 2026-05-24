"""
storage.py — Persistencia SQLite com aiosqlite.

Funcoes principais (contrato):
  init_db(db_path) -> None
  save_quote(quote, db_path) -> None
  save_news_item(item, db_path) -> None         — UNIQUE guid, ignora duplicado
  save_alert_event(event, db_path) -> None
  get_recent_alert(ticker, within_minutes, db_path) -> AlertEvent | None
  get_news_since(ticker, since_dt, db_path) -> list[NewsItem]
  get_news_analyses_since(ticker, since_dt, db_path) -> list[NewsAnalysis]
  save_news_analysis(analysis, db_path) -> None
  is_news_item_seen(guid, db_path) -> bool
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

import aiosqlite

from .types import AlertEvent, NewsAnalysis, NewsItem, NewsSource, Quote, Sentiment, TriggerType

logger = logging.getLogger(__name__)

_CREATE_QUOTES = """
CREATE TABLE IF NOT EXISTS quotes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    price REAL NOT NULL,
    change REAL NOT NULL,
    change_pct REAL NOT NULL,
    day_high REAL NOT NULL,
    day_low REAL NOT NULL,
    previous_close REAL NOT NULL,
    volume INTEGER NOT NULL,
    market_time TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    delay_minutes REAL NOT NULL,
    currency TEXT NOT NULL DEFAULT 'BRL'
);
"""

_CREATE_NEWS_ITEMS = """
CREATE TABLE IF NOT EXISTS news_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guid TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    source TEXT NOT NULL,
    published_at TEXT NOT NULL,
    url TEXT NOT NULL,
    tickers TEXT NOT NULL,
    body TEXT,
    cvm_protocolo TEXT,
    cvm_link_download TEXT,
    encoding_source TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

_CREATE_ALERT_EVENTS = """
CREATE TABLE IF NOT EXISTS alert_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    trigger_fired INTEGER NOT NULL DEFAULT 1,
    trigger_type TEXT NOT NULL,
    trigger_value REAL NOT NULL,
    price_at_trigger REAL NOT NULL,
    buy_price REAL,
    pct_from_buy REAL,
    fired_at TEXT NOT NULL
);
"""

_CREATE_NEWS_ANALYSES = """
CREATE TABLE IF NOT EXISTS news_analyses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    news_guid TEXT NOT NULL,
    ticker TEXT NOT NULL,
    sentiment TEXT NOT NULL,
    summary TEXT NOT NULL,
    analyzed_at TEXT NOT NULL,
    model TEXT NOT NULL,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0
);
"""

_CREATE_CVM_SEEN = """
CREATE TABLE IF NOT EXISTS cvm_seen_protocols (
    protocolo TEXT PRIMARY KEY,
    seen_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


async def init_db(db_path: str) -> None:
    """Cria todas as tabelas se nao existirem."""
    async with aiosqlite.connect(db_path) as db:
        await db.execute(_CREATE_QUOTES)
        await db.execute(_CREATE_NEWS_ITEMS)
        await db.execute(_CREATE_ALERT_EVENTS)
        await db.execute(_CREATE_NEWS_ANALYSES)
        await db.execute(_CREATE_CVM_SEEN)
        await db.commit()
    logger.debug("DB inicializado em %s", db_path)


def _dt_to_str(dt: datetime) -> str:
    return dt.isoformat()


def _str_to_dt(s: str) -> datetime:
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


async def save_quote(quote: Quote, db_path: str) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """INSERT INTO quotes
               (symbol, price, change, change_pct, day_high, day_low, previous_close,
                volume, market_time, fetched_at, delay_minutes, currency)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                quote.symbol,
                quote.price,
                quote.change,
                quote.change_pct,
                quote.day_high,
                quote.day_low,
                quote.previous_close,
                quote.volume,
                _dt_to_str(quote.market_time),
                _dt_to_str(quote.fetched_at),
                quote.delay_minutes,
                quote.currency,
            ),
        )
        await db.commit()


async def save_news_item(item: NewsItem, db_path: str) -> None:
    """Insere NewsItem. Se guid ja existe, ignora silenciosamente (dedup)."""
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """INSERT OR IGNORE INTO news_items
               (guid, title, source, published_at, url, tickers, body,
                cvm_protocolo, cvm_link_download, encoding_source)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                item.guid,
                item.title,
                item.source.value,
                _dt_to_str(item.published_at),
                item.url,
                json.dumps(item.tickers),
                item.body,
                item.cvm_protocolo,
                item.cvm_link_download,
                item.encoding_source,
            ),
        )
        await db.commit()


async def save_alert_event(event: AlertEvent, db_path: str) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """INSERT INTO alert_events
               (ticker, trigger_fired, trigger_type, trigger_value, price_at_trigger,
                buy_price, pct_from_buy, fired_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                event.ticker,
                1 if event.trigger_fired else 0,
                event.trigger_type.value,
                event.trigger_value,
                event.price_at_trigger,
                event.buy_price,
                event.pct_from_buy,
                _dt_to_str(event.fired_at),
            ),
        )
        await db.commit()


async def get_recent_alert(ticker: str, within_minutes: int, db_path: str) -> AlertEvent | None:
    """
    Retorna o AlertEvent mais recente para o ticker dentro da janela de cooldown,
    ou None se nenhum foi disparado recentemente.
    """
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT * FROM alert_events
               WHERE ticker = ?
               AND datetime(fired_at) >= datetime('now', ? || ' minutes')
               ORDER BY fired_at DESC LIMIT 1""",
            (ticker, f"-{within_minutes}"),
        ) as cursor:
            row = await cursor.fetchone()
            if row is None:
                return None
            return AlertEvent(
                ticker=row["ticker"],
                trigger_fired=bool(row["trigger_fired"]),
                trigger_type=TriggerType(row["trigger_type"]),
                trigger_value=row["trigger_value"],
                price_at_trigger=row["price_at_trigger"],
                buy_price=row["buy_price"],
                pct_from_buy=row["pct_from_buy"],
                fired_at=_str_to_dt(row["fired_at"]),
            )


async def get_news_since(ticker: str, since_dt: datetime, db_path: str) -> list[NewsItem]:
    """Retorna NewsItems do ticker publicados desde since_dt."""
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT * FROM news_items
               WHERE datetime(published_at) >= datetime(?)
               ORDER BY published_at DESC""",
            (_dt_to_str(since_dt),),
        ) as cursor:
            rows = await cursor.fetchall()

    results: list[NewsItem] = []
    for row in rows:
        tickers: list[str] = json.loads(row["tickers"])
        if ticker in tickers:
            results.append(
                NewsItem(
                    guid=row["guid"],
                    title=row["title"],
                    source=NewsSource(row["source"]),
                    published_at=_str_to_dt(row["published_at"]),
                    url=row["url"],
                    tickers=tickers,
                    body=row["body"],
                    cvm_protocolo=row["cvm_protocolo"],
                    cvm_link_download=row["cvm_link_download"],
                    encoding_source=row["encoding_source"],
                )
            )
    return results


async def save_news_analysis(analysis: NewsAnalysis, db_path: str) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """INSERT INTO news_analyses
               (news_guid, ticker, sentiment, summary, analyzed_at, model, input_tokens, output_tokens)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                analysis.news_guid,
                analysis.ticker,
                analysis.sentiment.value,
                analysis.summary,
                _dt_to_str(analysis.analyzed_at),
                analysis.model,
                analysis.input_tokens,
                analysis.output_tokens,
            ),
        )
        await db.commit()


async def get_news_analyses_since(ticker: str, since_dt: datetime, db_path: str) -> list[NewsAnalysis]:
    """Retorna NewsAnalyses para o ticker analisadas desde since_dt."""
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT * FROM news_analyses
               WHERE ticker = ? AND datetime(analyzed_at) >= datetime(?)
               ORDER BY analyzed_at DESC""",
            (ticker, _dt_to_str(since_dt)),
        ) as cursor:
            rows = await cursor.fetchall()

    return [
        NewsAnalysis(
            news_guid=row["news_guid"],
            ticker=row["ticker"],
            sentiment=Sentiment(row["sentiment"]),
            summary=row["summary"],
            analyzed_at=_str_to_dt(row["analyzed_at"]),
            model=row["model"],
            input_tokens=row["input_tokens"],
            output_tokens=row["output_tokens"],
        )
        for row in rows
    ]


async def is_news_item_seen(guid: str, db_path: str) -> bool:
    """Verifica se guid ja existe no storage (dedup sem inserir)."""
    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            "SELECT 1 FROM news_items WHERE guid = ? LIMIT 1", (guid,)
        ) as cursor:
            row = await cursor.fetchone()
            return row is not None


async def mark_cvm_protocol_seen(protocolo: str, db_path: str) -> bool:
    """
    Marca protocolo CVM como visto.
    Retorna True se era novo (inserido), False se ja existia.
    """
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            "INSERT OR IGNORE INTO cvm_seen_protocols (protocolo) VALUES (?)",
            (protocolo,),
        )
        await db.commit()
        return cursor.rowcount > 0


async def is_cvm_protocol_seen(protocolo: str, db_path: str) -> bool:
    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            "SELECT 1 FROM cvm_seen_protocols WHERE protocolo = ? LIMIT 1", (protocolo,)
        ) as cursor:
            row = await cursor.fetchone()
            return row is not None
