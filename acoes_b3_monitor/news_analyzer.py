"""
news_analyzer.py — Analise de sentimento de noticias via Anthropic Claude.

Funcao principal:
  analyze(item, settings) -> NewsAnalysis

Detalhes:
- Model default: claude-haiku-4-5-20251001 (configuravel via ANTHROPIC_MODEL)
- Prompt caching no system prompt (cache_control ephemeral — reduz custo em chamadas repetidas)
- Saida: JSON estruturado {sentiment, summary}
- Fronteira dura: system prompt proibe explicitamente previsao de preco/recomendacao
- Loga input_tokens e output_tokens por chamada
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone

import anthropic

from .config import get_anthropic_model
from .types import NewsAnalysis, NewsItem, Sentiment, Settings

logger = logging.getLogger(__name__)

# Cliente AsyncAnthropic reutilizado (module-level lazy) — evita criar um cliente por NewsItem
# e nao bloqueia o event loop (AsyncAnthropic usa httpx async internamente).
_async_client: anthropic.AsyncAnthropic | None = None


def _get_async_client(api_key: str) -> anthropic.AsyncAnthropic:
    """Retorna instancia lazy de AsyncAnthropic (singleton por processo)."""
    global _async_client
    if _async_client is None:
        _async_client = anthropic.AsyncAnthropic(api_key=api_key)
    return _async_client


# System prompt fixo — candidato a cache (mesmo conteudo repetido a cada chamada)
_SYSTEM_PROMPT = """Voce e um analista de noticias financeiras especializado em empresas brasileiras listadas na B3.

Dado o titulo e resumo de uma noticia sobre uma empresa, responda EXCLUSIVAMENTE em JSON valido com esta estrutura:
{"sentiment": "POSITIVO|NEUTRO|NEGATIVO", "summary": "<1-4 frases em PT-BR>"}

Regras OBRIGATORIAS que voce NUNCA pode violar:
1. NUNCA preveja precos, alvos de preco, valorizacao ou desvalorizacao esperada.
2. NUNCA diga "compre", "venda", "recomendo" ou qualquer variante.
3. NUNCA calcule ou projete ganho, perda, rentabilidade ou retorno financeiro.
4. APENAS: classifique o sentimento (POSITIVO/NEUTRO/NEGATIVO) e resuma o contexto factual em ate 4 frases curtas.
5. O resumo deve ser factual, objetivo e em PT-BR.
6. Responda SOMENTE o JSON, sem texto adicional antes ou depois."""

_MAX_TOKENS = 256


def _extract_json(text: str) -> dict:
    """
    Extrai JSON da resposta do Claude.
    Tenta parse direto; se falhar, busca bloco JSON com regex.
    """
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Tenta extrair bloco JSON com regex
        match = re.search(r"\{.*?\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
    raise ValueError(f"Nao foi possivel extrair JSON da resposta: {text[:200]}")


async def analyze(
    item: NewsItem,
    settings: Settings,
    model: str | None = None,
) -> NewsAnalysis:
    """
    Analisa NewsItem com Claude e retorna NewsAnalysis.

    Usa prompt caching no system prompt para reduzir custo.
    Loga tokens consumidos por chamada.
    """
    model_name = model or get_anthropic_model()
    client = _get_async_client(settings.anthropic_api_key)

    # Monta o conteudo da noticia para o user message
    ticker_str = ", ".join(item.tickers) if item.tickers else "N/A"
    user_content = f"Ticker(s): {ticker_str}\nTitulo: {item.title}"
    if item.body:
        # Trunca body para economizar tokens (primeiros 500 chars sao suficientes)
        user_content += f"\nResumo: {item.body[:500]}"

    try:
        # Usa prompt caching no system prompt (bloco fixo repetido a cada chamada)
        response = await client.messages.create(
            model=model_name,
            max_tokens=_MAX_TOKENS,
            system=[
                {
                    "type": "text",
                    "text": _SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[
                {"role": "user", "content": user_content},
                # Prefill para forcar saida JSON
                {"role": "assistant", "content": "{"},
            ],
        )

        input_tokens = response.usage.input_tokens
        output_tokens = response.usage.output_tokens
        logger.info(
            "news_analyzer: %s — tokens in=%d out=%d model=%s",
            item.guid,
            input_tokens,
            output_tokens,
            model_name,
        )

        # Reconstroi o JSON (prefill adicionou "{" que o Claude continuou)
        raw_text = "{" + (response.content[0].text if response.content else "")
        data = _extract_json(raw_text)

        sentiment_raw = data.get("sentiment", "NEUTRO").upper()
        try:
            sentiment = Sentiment(sentiment_raw)
        except ValueError:
            logger.warning("Sentimento invalido '%s'; usando NEUTRO", sentiment_raw)
            sentiment = Sentiment.NEUTRO

        summary = data.get("summary", "").strip()
        if not summary:
            summary = "Sem resumo disponivel."

        return NewsAnalysis(
            news_guid=item.guid,
            ticker=item.tickers[0] if item.tickers else "N/A",
            sentiment=sentiment,
            summary=summary,
            analyzed_at=datetime.now(tz=timezone.utc),
            model=model_name,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    except anthropic.APIError as e:
        logger.error("Anthropic API error para %s: %s", item.guid, e)
        raise
