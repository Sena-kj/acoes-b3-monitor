"""
briefing_builder.py — Agrega Quote[] + NewsAnalysis[] em DailyBriefing.

Funcao principal:
  build(quotes, news_analyses, settings) -> DailyBriefing

O resumo global (DailyBriefing.summary) e gerado pelo Claude com base nas
analises individuais. Fronteira dura aplica-se aqui tambem.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import anthropic
import pytz

from .config import get_anthropic_model
from .news_analyzer import _get_async_client
from .types import DailyBriefing, NewsAnalysis, Quote, Sentiment, Settings

logger = logging.getLogger(__name__)

BRT = pytz.timezone("America/Sao_Paulo")

_BRIEFING_SYSTEM_PROMPT = """Voce e um assistente que gera resumos diarios de carteira de acoes B3.

Dado um JSON com cotacoes e analises de noticias das ultimas 24h, escreva um resumo factual do dia em 1-3 frases em PT-BR.

Regras OBRIGATORIAS:
1. NUNCA preveja precos futuros, valorizacao ou desvalorizacao esperada.
2. NUNCA diga "compre", "venda" ou qualquer recomendacao de investimento.
3. NUNCA calcule ou projete ganho, perda ou rentabilidade.
4. Apenas sintetize factualmente o que aconteceu hoje (sentimentos dominantes, eventos relevantes).
5. Maximo 3 frases curtas e objetivas."""


async def _generate_summary(
    quotes: list[Quote],
    news_analyses: dict[str, list[NewsAnalysis]],
    settings: Settings,
) -> str:
    """Gera resumo do dia via Claude. Usa prompt caching no system prompt."""
    model_name = get_anthropic_model()
    client = _get_async_client(settings.anthropic_api_key)

    # Monta payload de contexto para o modelo
    context: dict = {
        "cotacoes": [
            {
                "ticker": q.symbol,
                "preco": q.price,
                "variacao_pct": q.change_pct,
            }
            for q in quotes
        ],
        "noticias_24h": {
            ticker: [
                {"sentimento": a.sentiment.value, "resumo": a.summary}
                for a in analyses
            ]
            for ticker, analyses in news_analyses.items()
            if analyses
        },
    }

    user_content = f"Dados da carteira:\n{json.dumps(context, ensure_ascii=False, indent=2)}"

    try:
        response = await client.messages.create(
            model=model_name,
            max_tokens=256,
            system=[
                {
                    "type": "text",
                    "text": _BRIEFING_SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user_content}],
        )
        logger.info(
            "briefing_builder summary: tokens in=%d out=%d",
            response.usage.input_tokens,
            response.usage.output_tokens,
        )
        return response.content[0].text.strip() if response.content else ""
    except anthropic.APIError as e:
        logger.error("Erro ao gerar resumo do briefing: %s", e)
        return "Resumo indisponivel."


async def build(
    quotes: list[Quote],
    news_analyses: dict[str, list[NewsAnalysis]],
    settings: Settings,
    generate_summary: bool = True,
) -> DailyBriefing:
    """
    Constroi DailyBriefing.

    quotes: lista de Quote recentes (um por ticker)
    news_analyses: dict ticker -> lista de NewsAnalysis das ultimas 24h
    generate_summary: False em testes para evitar chamada de API
    """
    now_utc = datetime.now(tz=timezone.utc)
    briefing_date = now_utc.astimezone(BRT).strftime("%Y-%m-%d")

    summary = ""
    if generate_summary and quotes:
        try:
            summary = await _generate_summary(quotes, news_analyses, settings)
        except Exception as e:
            logger.error("briefing_builder: falha ao gerar summary: %s", e)
            summary = "Resumo indisponivel."

    return DailyBriefing(
        quotes=quotes,
        news_by_ticker=news_analyses,
        summary=summary,
        generated_at=now_utc,
        briefing_date=briefing_date,
    )
