---
status: completed
agent: code-reviewer
feature: acoes-b3-monitor
date: 2026-05-24
verdict: approved-with-comments
reviewed-commit: ce779a1
---

# Code Review Report --- acoes-b3-monitor

## Summary

APPROVED-WITH-COMMENTS --- 0 blockers, 2 high, 5 medium, 4 low.

Codigo bem estruturado para MVP. Scheduler 24/7 protegido com except Exception nos jobs (sem morte por falha pontual). Tratamento de encoding correto nas fontes RSS. Principais preocupacoes: (1) duplicacao do User-Agent hardcoded em 3 lugares e do objeto BRT em 3 modulos; (2) cliente Anthropic instanciado por chamada; (3) get_anthropic_model() e get_db_path() instanciam _EnvSettings a cada chamada quebrando o singleton; (4) SDK Anthropic sync bloqueando o event loop em funcoes async.

---

## Result

### acoes_b3_monitor/quote_collector.py

- **[HIGH] linha 110-116 e 139-145: log de delay duplicado.** BrapiProvider.fetch_quotes ja loga delay por ticker (linhas 110-116). A facade fetch_quotes volta a logar as mesmas informacoes (linhas 139-145). Em producao com 4 tickers, cada polling emite 8 linhas de log redundantes. A motivacao no python-dev-report (CA-02 falhava no mock) explica a origem, mas o resultado sao dois loggers disparando para o mesmo evento. O logger.info dentro de BrapiProvider deveria ser removido, ou o da facade deveria ser o unico.

- **[MEDIUM] linha 24-25 vs news_collector.py linha 34 vs scheduler.py linha 157: DEFAULT_USER_AGENT triplicado.** Constante identica definida em quote_collector.py:25 e news_collector.py:34. scheduler.py:157 usa a mesma string literalmente hardcoded dentro do closure _make_cvm_download_job sem importar a constante. Se a string mudar, ha 3 lugares para atualizar. Deve ser movida para config.py ou constants.py.

### acoes_b3_monitor/news_collector.py

- **[MEDIUM] linha 148: feedparser.parse(resp.text) no MoneyTimes pode reintroduzir problema de encoding.** Para InfoMoney, o dev corretamente decodifica resp.content como latin-1 e passa xml_text string para o feedparser. Para o MoneyTimes, usa resp.text --- que httpx decodifica usando o charset do header Content-Type. Se o Money Times declarar charset errado ou omitir, httpx pode usar UTF-8 e introduzir mojibake. Abordagem defensiva: passar resp.content (bytes) para o feedparser igual ao InfoMoney.

- **[MEDIUM] linha 284-331: fetch_cvm_ipe faz await dentro de with zipfile.ZipFile(...).** Abre um zipfile.ZipFile com context manager sincrono e dentro do loop faz await is_cvm_protocol_seen(...) e await mark_cvm_protocol_seen(...). IO sincrono e assincrono misturados dentro do mesmo bloco with. Para um ZIP com centenas de fatos relevantes, segura o context manager enquanto aguarda IO de rede. Recomendado: coletar rows numa lista, fechar o ZIP, depois iterar com awaits.

- **[LOW] linha 252: import csv e from datetime import date dentro da funcao.** Imports locais usados sem necessidade de evitar circulares. Ambos sao stdlib e devem ir para o topo do arquivo.

### acoes_b3_monitor/news_analyzer.py

- **[HIGH] linha 77 e 88-103: SDK Anthropic sincrono bloqueando event loop.** anthropic.Anthropic (nao AsyncAnthropic) usa chamadas bloqueantes. Chamar client.messages.create(...) dentro de async def bloqueia o event loop durante toda a chamada a API (~1-3s). Para um scheduler assincrono 24/7, isso congela o loop durante a analise de cada noticia. Deve usar anthropic.AsyncAnthropic e await client.messages.create(...). Mesmo problema em briefing_builder.py:71. Tambem: o cliente e instanciado por chamada sem fechar --- a cada NewsItem um novo cliente httpx interno e criado.

- **[LOW] linha 55-61: regex r"\{.*?\}" em _extract_json e non-greedy.** Com re.DOTALL, captura o primeiro {...} menor. Se Claude retornar JSON com objeto aninhado, o regex captura apenas ate o primeiro } interno. O prompt forca saida simples entao o risco e baixo, mas o fallback vai falhar silenciosamente. Preferir r"\{[^{}]*\}" ou logar o texto completo quando o parse falha.

### acoes_b3_monitor/config.py

- **[MEDIUM] linhas 163-171: get_db_path() e get_anthropic_model() instanciam _EnvSettings() sem cache.** get_settings() tem @lru_cache e e o singleton. Mas get_db_path() e get_anthropic_model() criam nova instancia de _EnvSettings a cada chamada. get_anthropic_model() e chamado dentro de cada analise Claude (news_analyzer.py:76, briefing_builder.py:45) --- uma instancia de BaseSettings por noticia analisada. Ambas deveriam extrair de get_settings() ou ter @lru_cache proprio.

### acoes_b3_monitor/scheduler.py

- **[LOW] linhas 31, notifier.py:32, briefing_builder.py:25: BRT = pytz.timezone("America/Sao_Paulo") duplicado em 3 modulos.** Mesmo objeto criado identicamente tres vezes. Deve ser extraido para config.py ou constants.py.

- **[LOW] linhas 62, 91, 126, 155 + main.py:78: await init_db(db_path) chamado 5 vezes.** init_db e chamado em main.py antes de subir o scheduler, e cada job re-executa init_db no inicio. Como usa CREATE TABLE IF NOT EXISTS e idempotente --- nao causa bug. Mas sao 4 chamadas redundantes de DB por rodada. Se for safety net intencional, vale comentario explicando; sem comentario parece redundante.

---

## Duplicacao entre modulos

| Constante/Objeto | Arquivos | Ocorrencias |
|---|---|---|
| DEFAULT_USER_AGENT string | quote_collector.py, news_collector.py, scheduler.py | 3 (sendo 1 inline) |
| BRT = pytz.timezone(...) | scheduler.py, notifier.py, briefing_builder.py | 3 |
| anthropic.Anthropic(api_key=...) instanciado por chamada | news_analyzer.py, briefing_builder.py | 2 |

## Over-engineering

Nenhum detectado. Abstracao QuoteProvider (Protocol) e justificada pelo contrato que ja prev troca de provider. _SafeScheduler e simples e cumpre proposito claro. Sem fabricas ou DI desnecessaria.

## Violacoes de fronteira

Nenhuma detectada. Apenas python-dev tocou em acoes_b3_monitor/ e tests/python/. DevOps-dev ficou em Dockerfile, docker-compose.yml e .env.example.

## Dead code

- types.py re-exporta Position mas nao e usado em nenhum modulo do pacote. Declarado no contrato mas nao utilizado no MVP. Baixo risco.

---

## Next steps

**python-dev (HIGH --- antes de producao):**
1. Substituir anthropic.Anthropic por anthropic.AsyncAnthropic em news_analyzer.py:77 e briefing_builder.py:46, usando await client.messages.create(...). Confirmar versao do SDK em pyproject.toml: se for >= 0.20, AsyncAnthropic ja existe. Alternativa se versao for antiga: asyncio.to_thread(client.messages.create, ...).
2. Remover log duplicado de delay de dentro de BrapiProvider.fetch_quotes (linhas 110-116) --- manter apenas o da facade.

**python-dev (MEDIUM --- recomendado pre-producao):**
- Extrair DEFAULT_USER_AGENT e BRT para config.py e importar de la em todos os modulos.
- Fazer get_db_path() e get_anthropic_model() ler de get_settings() em vez de criar nova _EnvSettings.
- Corrigir fetch_cvm_ipe para coletar rows antes de fazer awaits.
- Corrigir encoding MoneyTimes para usar resp.content (bytes) igual ao InfoMoney.

## Blockers / questions

- Versao do SDK anthropic em pyproject.toml nao foi inspecionada diretamente. Manager deve verificar se e >= 0.20 (tem AsyncAnthropic) antes de despachar correcao. Se for < 0.20, a correcao e asyncio.to_thread, nao troca de classe.
