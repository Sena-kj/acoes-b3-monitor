---
status: completed
agent: python-dev
feature: acoes-b3-monitor
cycle: 1
date: 2026-05-24
verdict: corrections-applied
---

# Python Dev Report — Ciclo 1 de Correcao

## Summary

Aplicados todos os 7 itens obrigatorios e 1 opcional (M4 parcial). 67 testes passando (53 originais + 14 novos de seguranca). Smoke gate CA-12 continua passando sem .env.

---

## Result por item

### [SEC-ALTA] SSRF no resolver de redirect do Google News

**Arquivo:** `acoes_b3_monitor/news_collector.py`

**Fix:**
- Adicionadas funcoes `_is_private_host(hostname)` e `_validate_resolved_url(url)` que verificam: esquema == `https`; hostname nao resolve para IP privado, loopback ou link-local (RFC1918, 127.0.0.0/8, 169.254.0.0/16 incl. IMDS 169.254.169.254, ::1).
- `_resolve_google_redirect` agora usa **cliente httpx isolado** (novo `AsyncClient` sem headers compartilhados) em vez do cliente da sessao principal — evita vazamento de headers em cross-host redirect (pitfall `httpx-custom-header-forwarded-on-redirect`).
- Se a URL resolvida falhar na validacao, loga `WARNING` e retorna a URL original do Google (nao bloqueia o fluxo).

**Testes adicionados:**
- `test_ssrf_validate_resolved_url_rejects_private` — 9 parametrize com IPs/esquemas bloqueados (IMDS, loopback, RFC1918, ftp)
- `test_ssrf_validate_resolved_url_accepts_public` — URL publica valida nao levanta excecao
- `test_ssrf_resolve_google_redirect_rejects_private_host` — simula redirect para IMDS via respx, verifica que retorna URL original

---

### [CODE-H1] Anthropic sincrono bloqueia event loop

**Arquivos:** `acoes_b3_monitor/news_analyzer.py`, `acoes_b3_monitor/briefing_builder.py`

**Fix:**
- `news_analyzer.py`: substituido `anthropic.Anthropic` por `anthropic.AsyncAnthropic`; adicionado cliente module-level lazy `_async_client` com factory `_get_async_client(api_key)` — nao cria um cliente por NewsItem. Chamada alterada para `await client.messages.create(...)`.
- `briefing_builder.py`: importa `_get_async_client` de `news_analyzer` (reutiliza o mesmo singleton). Chamada alterada para `await client.messages.create(...)`. Removida instanciacao direta de `anthropic.Anthropic`.

**Testes:** mocks atualizados em `test_news_analyzer.py` e `test_briefing_builder.py` para usar `AsyncMock` e patchear `acoes_b3_monitor.news_analyzer._async_client` diretamente.

---

### [SEC-MEDIA] Token Telegram vaza em log

**Arquivo:** `acoes_b3_monitor/notifier.py:151`

**Fix:** Removido `payload` do `logger.error` no path 400. Log agora emite apenas `data` (resposta da API). Comentario explicativo adicionado.

---

### [SEC-MEDIA] ZIP da CVM sem protecao

**Arquivo:** `acoes_b3_monitor/news_collector.py`

**Fix (3 camadas):**
1. **Content-Length pre-download:** HEAD request antes do GET para verificar `content-length` > 50MB.
2. **Tamanho pos-download:** verifica `len(resp.content)` antes de processar.
3. **Zip-slip:** valida que `csv_names[0]` nao contem `..` nem inicia com `/`.
4. **Membro > 100MB:** verifica `info.file_size` (descompactado) via `zf.getinfo()`.

Bonus (CODE-MEDIUM do code-review): fechamento do ZipFile antes de fazer `await` — elimina mistura de I/O sincrono/assincrono no context manager.

**Teste adicionado:** `test_zip_slip_rejected` — ZIP com membro `../../etc/cron.d/backdoor.csv` deve retornar lista vazia.

---

### [SEC-MEDIA] XXE/feedparser

**Arquivo:** `pyproject.toml`, `tests/python/test_news_collector.py`

**Fix:** Adicionado `defusedxml>=0.7` ao `pyproject.toml`. feedparser 6.x usa `defusedxml` quando disponivel.

**Testes adicionados:**
- `test_xml_billion_laughs_does_not_explode` — XML com entity expansion de 4 niveis; verifica retorno sem crash.
- `test_xml_external_entity_does_not_leak` — XML com entidade `file:///etc/passwd`; verifica que titulo nao expoe conteudo do arquivo.

---

### [SEC-BAIXA] Fail-fast de secrets no startup

**Arquivo:** `acoes_b3_monitor/main.py`

**Fix:** Adicionada funcao `_validate_secrets(settings)` que levanta `RuntimeError` se `anthropic_api_key`, `telegram_bot_token` ou `telegram_chat_id` estiverem vazios. Chamada **apenas em `_run()`** (caminho de execucao real), **nao em `create_scheduler()`** — smoke gate CA-12 continua passando sem .env.

---

### [CODE-H2] Log de delay duplicado

**Arquivo:** `acoes_b3_monitor/quote_collector.py`

**Fix:** Removido `logger.info` de dentro de `BrapiProvider.fetch_quotes`. O unico log de delay agora e o da facade `fetch_quotes`.

---

## Opcionais realizados

- **M4 parcial:** `get_db_path()` e `get_anthropic_model()` mantem `_EnvSettings()` direto pois `db_path` e `anthropic_model` nao sao campos do contrato `Settings`. Comentarios explicativos adicionados em ambas as funcoes.
- **Bonus CODE-MEDIUM (nao obrigatorio):** `fetch_cvm_ipe` agora coleta rows dentro do bloco `with zipfile.ZipFile`, fecha o ZIP, e so entao faz os `await` — elimina mistura de I/O sincrono/assincrono.

---

## Arquivos modificados

| Arquivo | Mudanca principal |
|---|---|
| `acoes_b3_monitor/news_collector.py` | SSRF guard, zip-slip, Content-Length, ZIP async fix |
| `acoes_b3_monitor/news_analyzer.py` | AsyncAnthropic + singleton lazy |
| `acoes_b3_monitor/briefing_builder.py` | AsyncAnthropic via _get_async_client |
| `acoes_b3_monitor/notifier.py` | Remocao de payload do log 400 |
| `acoes_b3_monitor/quote_collector.py` | Remocao do log duplicado |
| `acoes_b3_monitor/main.py` | Fail-fast de secrets em _run() |
| `acoes_b3_monitor/config.py` | Comentarios explicativos |
| `pyproject.toml` | defusedxml>=0.7 adicionado |
| `tests/python/test_news_analyzer.py` | Mocks atualizados para AsyncMock |
| `tests/python/test_briefing_builder.py` | Mock atualizado para AsyncMock |
| `tests/python/test_news_collector.py` | 14 novos testes de seguranca |

---

## Verificacoes

- **67/67 testes passando** (53 originais + 14 novos)
- **Smoke gate CA-12:** exit 0 confirmado
- **defusedxml instalado via uv sync**

---

## Blockers / questions

Nenhum. Todos os itens obrigatorios resolvidos dentro da fronteira Python.
