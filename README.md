# acoes-b3-monitor

Monitor de ações da B3 que roda 24/7 num VPS: acompanha cotações, dispara alertas de preço, coleta notícias e fatos relevantes da CVM, classifica cada notícia com o Claude (Anthropic) e manda tudo pelo Telegram, incluindo um briefing diário.

## Stack

- Python 3.11+ assíncrono: `httpx`, `aiosqlite`, `pydantic-settings`
- APScheduler 3 (AsyncIOScheduler, fuso `America/Sao_Paulo`)
- Anthropic SDK (Claude Haiku por padrão) para análise de notícias
- `feedparser` + `defusedxml` para RSS; brapi.dev para cotações; Telegram Bot API para notificações
- SQLite para histórico, deduplicação e cooldown
- Docker multi-stage + Docker Compose; testes com pytest, pytest-asyncio e respx

## Destaques técnicos

- **Quatro jobs agendados** (`scheduler.py`): cotações a cada 5 min só no pregão (seg a sex, 09:45 às 17:30 BRT), notícias a cada 30 min, download diário do CVM IPE às 06:00 e briefing no horário configurado.
- **Alertas por ativo** configurados no `.env`: gatilho por preço absoluto (`price:42.00`) ou queda percentual sobre o preço médio (`pct:5`), com cooldown persistido no SQLite para não repetir alerta.
- **Fontes de notícia**: InfoMoney, Money Times (feed por empresa), Google News e fatos relevantes da CVM (ZIP com CSV latin-1, deduplicado por protocolo).
- **Análise com LLM barata**: system prompt com `cache_control` (prompt caching), prefill de `{` para forçar JSON, corpo truncado e log de tokens por chamada.
- **Hardening**: guarda contra SSRF ao seguir redirects do Google News (bloqueia RFC1918, loopback e 169.254.169.254), limites de tamanho no download e na descompactação do ZIP da CVM, proteção contra zip-slip e XML parseado com `defusedxml`.
- **Telegram resiliente**: retry em HTTP 429 respeitando `retry_after` e truncamento em 4096 caracteres.
- **Container enxuto**: imagem multi-stage, usuário não-root, volume nomeado para o SQLite e limite de 256 MB de RAM.
- **~80 testes** cobrindo coletores (HTTP mockado com respx), motor de alertas, storage, briefing, notifier e a configuração do Compose.

## Como rodar

```bash
cp .env.example .env    # preencha TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID e ANTHROPIC_API_KEY
```

Com Docker (como roda em produção):

```bash
docker compose up -d --build
docker compose logs -f monitor
```

Local, com [uv](https://docs.astral.sh/uv/):

```bash
uv sync
uv run acoes-b3-monitor
uv run pytest
```

Guia de deploy em VPS Ubuntu: [`deploy/README.md`](deploy/README.md) (script `deploy/deploy.sh` faz pull e rebuild).

## Estrutura

```
acoes_b3_monitor/
  main.py              entrypoint
  scheduler.py         jobs do APScheduler
  quote_collector.py   cotações (brapi.dev, provider plugável)
  news_collector.py    RSS + CVM IPE, com guarda de SSRF
  news_analyzer.py     classificação de notícias com Claude
  alert_engine.py      regras de alerta e cooldown
  briefing_builder.py  briefing diário
  notifier.py          envio pelo Telegram
  storage.py           SQLite assíncrono
tests/                 pytest (python/ e deploy/)
deploy/                guia e script de deploy no VPS
Dockerfile, docker-compose.yml
```

## English

Async Python service that monitors B3 (Brazilian stock exchange) tickers, fires price alerts and pushes news to Telegram.
News and CVM filings are classified by Claude with prompt caching; scheduling runs on APScheduler with market-hours windows.
Ships as a non-root multi-stage Docker image with SQLite persistence and an ~80-test pytest suite.
