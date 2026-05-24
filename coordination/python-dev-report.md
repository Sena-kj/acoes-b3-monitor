---
status: completed
agent: python-dev
feature: acoes-b3-monitor
date: 2026-05-24
---

## Summary

Pacote `acoes_b3_monitor/` implementado completo. 10 modulos Python criados conforme spec + contrato. 53 testes pytest passando (0 falhas). Smoke gate (`create_scheduler + shutdown`) confirma exit 0. Nenhuma chamada de rede real nos testes — todos mockados com respx/unittest.mock usando payloads do research real.

## Result

### Arquivos criados

**Pacote principal** (`acoes_b3_monitor/`):
- `__init__.py` — marker do pacote
- `types.py` — re-exporta todos os contract types de `coordination/_contract_types.py`
- `config.py` — `get_settings()` singleton via Pydantic BaseSettings; parseia `TICKER_ALERT_TRIGGER` (price: e pct:); constantes de mapeamento ticker->slug MoneyTimes/Google/CVM
- `storage.py` — SQLite com aiosqlite; tabelas: quotes, news_items, alert_events, news_analyses, cvm_seen_protocols; dedup por GUID UNIQUE + cvm_seen_protocols; cooldown query com `datetime('now', '-N minutes')`
- `quote_collector.py` — `BrapiProvider` + Protocol `QuoteProvider`; `fetch_quotes()` facade; loga `delay=Nmin` por ticker (CA-02); trata 401 MISSING_TOKEN vs INVALID_TOKEN separadamente
- `news_collector.py` — `fetch_news()` (InfoMoney RSS latin-1 + MoneyTimes UTF-8 tag-feed + Google News com redirect resolver); `fetch_cvm_ipe()` (ZIP CVM, CSV latin-1, dedup por protocolo); dedup intra-batch por guid antes do storage
- `alert_engine.py` — `evaluate()` com TriggerType.PRICE e PCT; lookup O(1) por symbol; dedup via `get_recent_alert` com cooldown configuravel
- `news_analyzer.py` — SDK anthropic com prompt caching (cache_control ephemeral no system prompt); prefill `{` para forcar JSON; fallback NEUTRO em sentimento invalido; loga tokens in/out
- `briefing_builder.py` — `build()` agrega quotes + analyses; `_generate_summary()` com prompt caching
- `notifier.py` — `send_message/alert/news_analysis/briefing` via httpx; retry em 429; trunca a 4096 chars; formata mensagens conforme spec UX
- `scheduler.py` — `create_scheduler()` com 4 jobs (quote_poll IntervalTrigger, news_fetch IntervalTrigger, briefing CronTrigger, cvm_download CronTrigger); logica de pregao dentro do job quote_poll (nao no trigger — mais flexivel); timezone America/Sao_Paulo
- `main.py` — `create_scheduler()` publica com `_SafeScheduler` wrapper (suprime `SchedulerNotRunningError` no smoke gate); `main()` asyncio com SIGINT/SIGTERM graceful

**Infra**:
- `pyproject.toml` — deps: httpx, feedparser, apscheduler<4, pydantic-settings, anthropic, aiosqlite, pytz, python-dateutil; entrypoint `acoes-b3-monitor`

**Testes** (`tests/python/`):
- `conftest.py` — fixtures Quote/AlertRule/NewsItem/NewsAnalysis/Settings/tmp_db; payload brapi real do research
- `test_alert_engine.py` — CA-03, CA-04, CA-05, CA-06 (8 testes)
- `test_briefing_builder.py` — CA-10 (6 testes)
- `test_main.py` — CA-12 (5 testes)
- `test_news_analyzer.py` — CA-09 + helpers (8 testes)
- `test_news_collector.py` — CA-07, CA-08 (4 testes)
- `test_notifier.py` — CA-11 (6 testes)
- `test_quote_collector.py` — CA-01, CA-02 (6 testes)
- `test_storage.py` — storage primitivas + dedup/cooldown (10 testes)

### Mapeamento CA → arquivo/teste

| CA | Descricao | Modulo | Teste |
|---|---|---|---|
| CA-01 | fetch_quotes retorna 4 Quote | quote_collector.py | test_quote_collector.py::test_ca01_* |
| CA-02 | delay_minutes calculado e logado | quote_collector.py (facade) | test_quote_collector.py::test_ca02_* |
| CA-03 | Alerta price dispara | alert_engine.py::_trigger_price | test_alert_engine.py::test_ca03_* |
| CA-04 | Alerta pct dispara | alert_engine.py::_trigger_pct | test_alert_engine.py::test_ca04_* |
| CA-05 | Alerta nao dispara fora do gatilho | alert_engine.py::evaluate | test_alert_engine.py::test_ca05_* |
| CA-06 | Dedup alertas 60min | alert_engine.py + storage.py | test_alert_engine.py::test_ca06_* |
| CA-07 | Noticia em PT sem mojibake | news_collector.py (latin-1 decode) | test_news_collector.py::test_ca07_* |
| CA-08 | Dedup noticias por guid | storage.py INSERT OR IGNORE | test_news_collector.py::test_ca08_* |
| CA-09 | Analise Claude com sentimento + summary | news_analyzer.py | test_news_analyzer.py::test_ca09_* |
| CA-10 | Briefing diario completo | briefing_builder.py | test_briefing_builder.py::test_ca10_* |
| CA-11 | Telegram entregue | notifier.py | test_notifier.py::test_ca11_* |
| CA-12 | Smoke import + invocacao | main.py::create_scheduler | test_main.py::test_ca12_* |

### Comandos

```bash
# Instalar dependencias (uv)
cd projects/acoes-b3-monitor
uv pip install -e .

# Rodar testes (com PYTHONPATH para coordination/)
uv run python -m pytest tests/python/ -v

# Smoke gate (CA-12)
uv run python -c "from acoes_b3_monitor.main import create_scheduler; s=create_scheduler(); s.shutdown(wait=False)"

# Subir em dev (copiar .env com tokens reais)
cp .env.example .env  # preencher tokens
uv run acoes-b3-monitor
```

### Resultado dos testes
```
53 passed in 7.71s
```

## Next steps

- [ ] Manager: merge da branch do python-dev no principal
- [ ] DevOps-dev: Dockerfile + entrypoint `uv run acoes-b3-monitor` (ou `python -m acoes_b3_monitor.main`); .env.example com todas as vars da spec
- [ ] QA: testar CA-09 manualmente (verificar que summary nao contem previsao de preco/recomendacao) com ANTHROPIC_API_KEY real
- [ ] QA: testar CA-11 com TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID reais
- [ ] Considerar: `conftest.py` injeta `coordination/` no sys.path — se o pacote for containerizado, sera necessario copiar `_contract_types.py` para dentro do pacote ou remover a re-exportacao via `coordination/`

## Dead-ends & detours

- **Tentei:** `scheduler.shutdown(wait=False)` no smoke gate — **Problema:** `SchedulerNotRunningError` quando scheduler nao foi `.start()`-ado — **Virei pra:** `_SafeScheduler` wrapper em `main.py` que suprime silenciosamente o erro no shutdown de scheduler nao iniciado
- **Tentei:** log de `delay=Nmin` apenas dentro de `BrapiProvider.fetch_quotes` — **Problema:** o mock de provider nos testes nao chama o logger do BrapiProvider, CA-02 falhava — **Virei pra:** log na facade `fetch_quotes()` (apos o provider retornar), garantindo o log independente do provider usado

## Blockers / questions

- **_contract_types.py em `coordination/`:** o pacote importa de `coordination._contract_types` que precisa estar no `PYTHONPATH`. Em producao (container), ou copiamos o arquivo para dentro do pacote, ou montamos o volume correto. Sugestao: DevOps-dev considerar `PYTHONPATH=/app:/app/coordination` no Dockerfile.
- **Modelo Anthropic:** o contrato `api-contract.yaml` menciona `claude-haiku-3-5` mas as instrucoes da task especificam `claude-haiku-4-5-20251001`. Implementei com o modelo correto das instrucoes (`claude-haiku-4-5-20251001`) como default via `ANTHROPIC_MODEL`. O contrato YAML esta desatualizado nesse ponto.
- **CA-12 no contexto real:** smoke gate sem `.env` gera warnings de ALERT_TRIGGER ausente (esperado — nao e erro fatal). Com `.env` real os warnings somem.
