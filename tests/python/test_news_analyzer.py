"""
Testes CA-09 — news_analyzer.

CA-09: analyze(item) retorna NewsAnalysis com:
  - sentiment em {POSITIVO, NEUTRO, NEGATIVO}
  - summary com 1-4 frases (string nao vazia)
  - NÃO contem previsao de preco, ganho/perda ou recomendacao (verificacao manual QA)
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from acoes_b3_monitor.news_analyzer import _extract_json, analyze
from acoes_b3_monitor.types import NewsAnalysis, NewsItem, Sentiment


# ---------------------------------------------------------------------------
# Helpers para mock do SDK Anthropic
# ---------------------------------------------------------------------------

def _make_anthropic_response(sentiment: str, summary: str) -> MagicMock:
    """Cria mock de anthropic.types.Message com payload de analise."""
    content_text = json.dumps({"sentiment": sentiment, "summary": summary})
    # O prefill adiciona "{" antes, entao o .text comeca apos "{"
    content_without_brace = content_text[1:]  # remove "{" inicial

    mock_content = MagicMock()
    mock_content.text = content_without_brace

    mock_usage = MagicMock()
    mock_usage.input_tokens = 120
    mock_usage.output_tokens = 48

    mock_response = MagicMock()
    mock_response.content = [mock_content]
    mock_response.usage = mock_usage

    return mock_response


# ---------------------------------------------------------------------------
# Testes
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ca09_analyze_returns_valid_sentiment(
    news_item_vale3: NewsItem,
    settings,
) -> None:
    """CA-09: sentiment deve ser um dos tres valores validos."""
    mock_response = _make_anthropic_response(
        "NEGATIVO",
        "Vale interrompeu operacoes em uma mina de MG por motivo tecnico. O incidente pode afetar volumes de producao.",
    )

    with patch("acoes_b3_monitor.news_analyzer.anthropic.Anthropic") as mock_anthropic_cls:
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response
        mock_anthropic_cls.return_value = mock_client

        analysis = await analyze(news_item_vale3, settings)

    assert analysis.sentiment in {Sentiment.POSITIVO, Sentiment.NEUTRO, Sentiment.NEGATIVO}
    assert analysis.sentiment == Sentiment.NEGATIVO


@pytest.mark.asyncio
async def test_ca09_analyze_summary_not_empty(
    news_item_vale3: NewsItem,
    settings,
) -> None:
    """CA-09: summary deve ser string nao vazia."""
    mock_response = _make_anthropic_response(
        "NEUTRO",
        "A empresa reportou incidente operacional. Os detalhes ainda estao sendo apurados.",
    )

    with patch("acoes_b3_monitor.news_analyzer.anthropic.Anthropic") as mock_anthropic_cls:
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response
        mock_anthropic_cls.return_value = mock_client

        analysis = await analyze(news_item_vale3, settings)

    assert isinstance(analysis.summary, str)
    assert len(analysis.summary.strip()) > 0, "summary nao pode ser vazia"


@pytest.mark.asyncio
async def test_ca09_analyze_tokens_logged(
    news_item_vale3: NewsItem,
    settings,
    caplog,
) -> None:
    """CA-09: tokens input e output devem ser logados e registrados no NewsAnalysis."""
    import logging

    mock_response = _make_anthropic_response("POSITIVO", "Noticia positiva para a empresa.")

    with patch("acoes_b3_monitor.news_analyzer.anthropic.Anthropic") as mock_anthropic_cls:
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response
        mock_anthropic_cls.return_value = mock_client

        with caplog.at_level(logging.INFO, logger="acoes_b3_monitor.news_analyzer"):
            analysis = await analyze(news_item_vale3, settings)

    assert analysis.input_tokens == 120
    assert analysis.output_tokens == 48
    assert analysis.model is not None and len(analysis.model) > 0

    # Verifica log de tokens
    token_logs = [r.message for r in caplog.records if "tokens" in r.message.lower()]
    assert len(token_logs) > 0, "Nenhum log de tokens encontrado"


@pytest.mark.asyncio
async def test_ca09_analyze_returns_newsanalysis_fields(
    news_item_vale3: NewsItem,
    settings,
) -> None:
    """CA-09: NewsAnalysis deve ter todos os campos obrigatorios."""
    mock_response = _make_anthropic_response("NEUTRO", "Analise de rotina sem impacto imediato.")

    with patch("acoes_b3_monitor.news_analyzer.anthropic.Anthropic") as mock_anthropic_cls:
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response
        mock_anthropic_cls.return_value = mock_client

        analysis = await analyze(news_item_vale3, settings)

    assert isinstance(analysis, NewsAnalysis)
    assert analysis.news_guid == news_item_vale3.guid
    assert analysis.ticker in news_item_vale3.tickers
    assert analysis.analyzed_at.tzinfo is not None
    assert analysis.model is not None


@pytest.mark.asyncio
async def test_ca09_analyze_invalid_sentiment_fallback(
    news_item_vale3: NewsItem,
    settings,
) -> None:
    """CA-09: Sentimento invalido da API deve fazer fallback para NEUTRO."""
    mock_response = _make_anthropic_response("INCERTO", "Situacao ambigua.")

    with patch("acoes_b3_monitor.news_analyzer.anthropic.Anthropic") as mock_anthropic_cls:
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response
        mock_anthropic_cls.return_value = mock_client

        analysis = await analyze(news_item_vale3, settings)

    assert analysis.sentiment == Sentiment.NEUTRO


def test_extract_json_direct() -> None:
    """_extract_json parseia JSON limpo."""
    result = _extract_json('{"sentiment": "POSITIVO", "summary": "Empresa teve bom resultado."}')
    assert result["sentiment"] == "POSITIVO"


def test_extract_json_with_preamble() -> None:
    """_extract_json extrai JSON mesmo com texto antes."""
    result = _extract_json('Aqui esta a analise: {"sentiment": "NEGATIVO", "summary": "Resultados abaixo."}')
    assert result["sentiment"] == "NEGATIVO"


def test_extract_json_invalid_raises() -> None:
    """_extract_json levanta ValueError em texto sem JSON."""
    with pytest.raises(ValueError, match="Nao foi possivel extrair JSON"):
        _extract_json("Esta e uma resposta sem JSON valido nenhum.")
