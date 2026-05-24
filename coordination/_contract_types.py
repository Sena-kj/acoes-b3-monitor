"""
Contract types for acoes-b3-monitor MVP.

Ground truth compartilhado entre todos os módulos (quote_collector, news_collector,
alert_engine, news_analyzer, briefing_builder, notifier, storage).

Regras:
- Nenhum módulo de app define seus próprios dataclasses para esses conceitos — importa daqui.
- Campos opcionais têm default=None; campos obrigatórios sem default.
- Todos os datetime são timezone-aware (UTC ou America/Sao_Paulo conforme documentado).
- Enums são strings para serialização fácil no SQLite.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Literal


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class Sentiment(str, Enum):
    POSITIVO = "POSITIVO"
    NEUTRO = "NEUTRO"
    NEGATIVO = "NEGATIVO"


class TriggerType(str, Enum):
    PRICE = "price"   # gatilho: price <= trigger_value (R$ absoluto)
    PCT = "pct"       # gatilho: price <= buy_price * (1 - trigger_value/100)


class NewsSource(str, Enum):
    INFOMONEY = "infomoney"
    MONEYTIMES = "moneytimes"
    GOOGLE_NEWS = "google_news"
    CVM_IPE = "cvm_ipe"
    MARKETAUX = "marketaux"   # reservado; não implementar no MVP


# ---------------------------------------------------------------------------
# Cotação (quote_collector)
# ---------------------------------------------------------------------------


@dataclass
class Quote:
    """
    Cotação pontual de um ativo retornada pelo provider (brapi.dev no MVP).

    market_time: timestamp do DADO em UTC (campo brapi 'regularMarketTime').
                 Representa quando a cotação foi gerada na bolsa (com delay ~15min no free).
    fetched_at:  timestamp do request em UTC (campo brapi 'requestedAt').
    delay_minutes: (fetched_at - market_time).total_seconds() / 60
                   Calculado pelo quote_collector, não pelo caller.
    """

    symbol: str                  # ex: "PETR4"
    price: float                 # regularMarketPrice (R$)
    change: float                # regularMarketChange (R$ vs fechamento anterior)
    change_pct: float            # regularMarketChangePercent (%)
    day_high: float              # regularMarketDayHigh
    day_low: float               # regularMarketDayLow
    previous_close: float        # regularMarketPreviousClose
    volume: int                  # regularMarketVolume
    market_time: datetime        # UTC, tzinfo obrigatório
    fetched_at: datetime         # UTC, tzinfo obrigatório
    delay_minutes: float         # calculado; >= 0
    currency: str = "BRL"


# ---------------------------------------------------------------------------
# Posição e regra de alerta (configuração do usuário)
# ---------------------------------------------------------------------------


@dataclass
class Position:
    """
    Representa a posição do usuário em um ativo.
    Lida do .env (PETR4_BUY_PRICE etc.) pelo config.py.
    """

    ticker: str          # ex: "PETR4"
    buy_price: float     # preço médio de compra (R$)


@dataclass
class AlertRule:
    """
    Regra de disparo de alerta para um ativo.
    Derivada do .env (PETR4_ALERT_TRIGGER).
    """

    ticker: str
    trigger_type: TriggerType
    trigger_value: float         # R$ absoluto (PRICE) ou % (PCT)
    buy_price: float | None      # obrigatório quando trigger_type == PCT


# ---------------------------------------------------------------------------
# Evento de alerta disparado (alert_engine)
# ---------------------------------------------------------------------------


@dataclass
class AlertEvent:
    """
    Produzido pelo alert_engine quando Quote satisfaz AlertRule.
    Persistido no storage para deduplicação (não disparar o mesmo alerta duas vezes
    dentro de 60 minutos).
    """

    ticker: str
    trigger_fired: bool                  # sempre True quando emitido; campo explícito p/ clareza
    trigger_type: TriggerType
    trigger_value: float                 # valor configurado
    price_at_trigger: float              # Quote.price no momento do disparo
    buy_price: float | None              # None se trigger_type == PRICE
    pct_from_buy: float | None           # (price - buy_price) / buy_price * 100; negativo = abaixo
    fired_at: datetime                   # UTC, tzinfo obrigatório


# ---------------------------------------------------------------------------
# Notícia coletada (news_collector)
# ---------------------------------------------------------------------------


@dataclass
class NewsItem:
    """
    Item de notícia normalizado, independente da fonte.

    guid:            identificador único do item no feed (RSS <guid> ou URL).
                     Para CVM IPE, usar Protocolo_Entrega.
                     UNIQUE no storage — base da deduplicação.
    cvm_protocolo:   Protocolo_Entrega do CVM IPE (None para fontes RSS).
    url:             URL real do artigo. Para Google News, DEVE ser a URL resolvida
                     após seguir o redirect (nunca armazenar o redirect ofuscado).
    body:            Texto do artigo. Pode ser None se só título disponível (RSS sem description).
    tickers:         Lista de tickers associados (inferida, não estruturada na fonte).
                     Pode ter mais de um ticker por notícia.
    encoding_source: Encoding original da fonte antes da normalização para UTF-8.
                     Informativo; todos os campos de texto aqui já são str Python (UTF-8).
    """

    guid: str
    title: str                          # UTF-8, sem HTML entities
    source: NewsSource
    published_at: datetime              # UTC, tzinfo obrigatório
    url: str                            # URL real (redirect resolvido se Google News)
    tickers: list[str]                  # ex: ["PETR4"]
    body: str | None = None             # texto do artigo (opcional)
    cvm_protocolo: str | None = None    # só para source == CVM_IPE
    cvm_link_download: str | None = None  # URL do RAD/PDF; só para source == CVM_IPE
    encoding_source: str | None = None  # ex: "latin-1"; documentativo


# ---------------------------------------------------------------------------
# Análise de notícia (news_analyzer — Claude API)
# ---------------------------------------------------------------------------


@dataclass
class NewsAnalysis:
    """
    Resultado da análise qualitativa de uma NewsItem pelo Claude.

    Fronteira dura: summary NÃO deve conter previsão de preço, ganho/perda
    financeira, recomendação de compra ou venda.
    Validado pelo system prompt; QA confirma manualmente.
    """

    news_guid: str               # FK para NewsItem.guid
    ticker: str
    sentiment: Sentiment
    summary: str                 # 1–4 frases, PT-BR
    analyzed_at: datetime        # UTC, tzinfo obrigatório
    model: str                   # ex: "claude-opus-4-5" — rastreabilidade de custo
    input_tokens: int            # tokens consumidos na análise
    output_tokens: int


# ---------------------------------------------------------------------------
# Briefing diário (briefing_builder)
# ---------------------------------------------------------------------------


@dataclass
class DailyBriefing:
    """
    Agregado do dia: cotações + análises de notícias das últimas 24h por ticker.

    quotes:          Quote mais recente de cada ticker monitorado.
    news_by_ticker:  Dict ticker -> lista de NewsAnalysis das últimas 24h.
                     Pode ser lista vazia se não houve notícias.
    summary:         Parágrafo de 1–3 frases gerado pelo Claude sobre o dia como um todo.
    generated_at:    Timestamp da geração (UTC).
    """

    quotes: list[Quote]
    news_by_ticker: dict[str, list[NewsAnalysis]]
    summary: str
    generated_at: datetime        # UTC, tzinfo obrigatório
    briefing_date: str            # "2026-05-24" — data de referência do briefing (BRT)


# ---------------------------------------------------------------------------
# Configuração (lida do .env por config.py)
# ---------------------------------------------------------------------------


@dataclass
class TickerConfig:
    """
    Configuração por ativo: posição + regra de alerta.
    Derivada do .env e repassada a todos os módulos via Settings.
    """

    ticker: str
    buy_price: float
    alert_rule: AlertRule


@dataclass
class Settings:
    """
    Configuração global da aplicação, lida do .env via Pydantic BaseSettings.
    Este dataclass é o contrato — a implementação em config.py deve expor
    um objeto compatível com todos esses campos.

    tickers:         Lista ordenada de tickers monitorados (max 4 no free).
    brapi_token:     None = free (só 4 tickers hardcoded). Str = plano pago.
    briefing_time:   "HH:MM" em BRT. Ex: "08:00".
    market_open:     Início do pregão BRT. Default "09:45".
    market_close:    Fim do pregão BRT. Default "17:30".
    alert_cooldown_minutes: Janela de deduplicação de alertas. Default 60.
    news_fetch_interval_minutes: Frequência da coleta de notícias. Default 30.
    quote_poll_interval_minutes: Frequência do polling de cotação. Default 5.
    """

    tickers: list[str]
    telegram_bot_token: str
    telegram_chat_id: str
    anthropic_api_key: str
    ticker_configs: dict[str, TickerConfig]   # keyed by ticker
    brapi_token: str | None = None
    briefing_time: str = "08:00"
    market_open: str = "09:45"
    market_close: str = "17:30"
    alert_cooldown_minutes: int = 60
    news_fetch_interval_minutes: int = 30
    quote_poll_interval_minutes: int = 5


# ---------------------------------------------------------------------------
# Tipos de provider (abstração de cotação)
# ---------------------------------------------------------------------------

# Protocol que qualquer provider de cotação deve satisfazer.
# Permite trocar brapi por outro provider sem reescrever alert_engine.
# Implementação concreta: services/providers/brapi_provider.py
#
# Interface esperada:
#   class QuoteProvider(Protocol):
#       async def fetch_quotes(self, tickers: list[str]) -> list[Quote]: ...
#
# O quote_collector.py instancia o provider configurado e delega a ele.
# No MVP, o único provider é BrapiProvider.

QuoteProviderLiteral = Literal["brapi"]   # extensível: "brapi" | "yahoo" | "status_invest"
