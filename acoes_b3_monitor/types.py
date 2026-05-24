"""
types.py — Re-exporta os contract types do pacote.

A fonte do contrato é coordination/_contract_types.py (escrito pelo PM).
Mantemos uma cópia sincronizada DENTRO do pacote (_contract_types.py) para que
o runtime não dependa de coordination/ — que é excluída do container
(.dockerignore). Ver pitfall: fixtures-direct-import-breaks-api-wiring.

Todos os modulos internos importam daqui (nao duplicam dataclasses).
"""

from __future__ import annotations

# Re-exporta tudo do contrato (cópia no pacote, não de coordination/)
from acoes_b3_monitor._contract_types import (
    AlertEvent,
    AlertRule,
    DailyBriefing,
    NewsAnalysis,
    NewsItem,
    NewsSource,
    Position,
    Quote,
    QuoteProviderLiteral,
    Sentiment,
    Settings,
    TickerConfig,
    TriggerType,
)

__all__ = [
    "AlertEvent",
    "AlertRule",
    "DailyBriefing",
    "NewsAnalysis",
    "NewsItem",
    "NewsSource",
    "Position",
    "Quote",
    "QuoteProviderLiteral",
    "Sentiment",
    "Settings",
    "TickerConfig",
    "TriggerType",
]
