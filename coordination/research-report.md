---
status: completed
agent: research
feature: acoes-b3-monitor
date: 2026-05-24
report-file: coordination/research-report.md
---

## Summary

- **Cotacao (brapi.dev):** confirmado empiricamente - gratis funciona SEM token apenas para 4 tickers (PETR4/VALE3/ITUB4/MGLU3). Qualquer outro ticker retorna `401 MISSING_TOKEN`, mesmo existindo. Para monitorar carteira real (>4 acoes) o plano pago e obrigatorio, nao opcional.
- **Noticias:** RSS PT (InfoMoney, Money Times, Google News) todos retornam XML valido HOJE e sao a fonte recomendada - gratis, sem rate limit pratico; Money Times tem feed por `/tag/<empresa>/feed/` (filtro por ticker nativo). Marketaux exige API key e o free corta para ~3 artigos/resposta - bom so pra sentimento de blue chips, nao pra cobertura.
- **Fatos relevantes (CVM):** viavel e robusto - CSV anual via dados.cvm.gov.br (dataset IPE), atualizado no mesmo dia (22/05 ja estava no arquivo em 24/05), filtrar `Categoria == "Fato Relevante"`. Fonte oficial, gratuita, sem auth. **Recomendacao: usar CVM IPE + RSS PT como fontes primarias; brapi pago para cotacao; Marketaux opcional so p/ sentimento EN.**

## Result

### Tabela por fonte (validado empiricamente - bati nos endpoints reais em 2026-05-24)

| Fonte | URL | Auth | Rate limit | Delay | Formato | Viavel? |
|---|---|---|---|---|---|---|
| **brapi.dev** quote | `https://brapi.dev/api/quote/<TICKER>` | **Gratis so p/ PETR4,VALE3,ITUB4,MGLU3 sem token.** Outros -> `?token=<TOKEN>` (query param) | Gratis 15k req/mes; Pro R$83/mes 500k | ~15min gratis / ~5min Pro | JSON `results[]` | SIM (pago p/ >4 acoes) |
| **Marketaux** news | `https://api.marketaux.com/v1/news/all?symbols=PETR4.SA&api_token=<KEY>` | `api_token` query param (obrigatorio) | 100 req/dia free; **free corta p/ ~3 artigos por resposta** | tempo quase real | JSON `data[]` com `entities[].sentiment_score` (-1..1) | PARCIAL (so sentimento blue chip) |
| **InfoMoney RSS** | `https://www.infomoney.com.br/feed/` e `.../mercados/feed/` | Nenhuma (User-Agent recomendado) | nenhum pratico | minutos | RSS 2.0 XML, encoding **latin-1/ISO-8859-1** | SIM |
| **Money Times RSS** | `https://www.moneytimes.com.br/feed/` **e `/tag/<empresa>/feed/`** | Nenhuma | nenhum pratico | minutos | RSS 2.0 XML | SIM (feed por tag = filtro por ticker gratis) |
| **Google News RSS** | `https://news.google.com/rss/search?q=<query>&hl=pt-BR&gl=BR&ceid=BR:pt-419` | Nenhuma | nenhum pratico (nao abusar) | minutos | RSS 2.0; **`<link>` e URL redirect ofuscada do Google**, nao a do veiculo | SIM |
| **CVM Fatos Relevantes (IPE)** | `https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/IPE/DADOS/ipe_cia_aberta_<ANO>.zip` | Nenhuma | nenhum | mesmo dia | ZIP -> CSV `;`-delim, **latin-1**, header com `Categoria`/`Nome_Companhia`/`Assunto`/`Link_Download` | SIM |
| **Anthropic API (analise)** | `https://api.anthropic.com/v1/messages` | `x-api-key` | tier-dependent | - | - | SIM (sem pattern no vault ainda - ver Blockers) |

### Capability verdict (hipoteses do plano de viabilidade)

- OK "brapi gratis cobre 4 acoes sem token" - **confirmado**: PETR4/VALE3/ITUB4/MGLU3 -> HTTP 200 sem token.
- FALSO "brapi gratis serve pra qualquer ticker da B3" - BBAS3 e ZZZZ99 -> `401 MISSING_TOKEN`. Gratis e hard-limited aos 4 tickers (nao e so rate limit, e allowlist de simbolo). A lista `/api/available` mostra ~todos os tickers mas so os 4 respondem sem token.
- OK "RSS InfoMoney/Money Times ativos" - confirmado, XML valido HOJE.
- OK "Google News RSS por empresa funciona" - confirmado (`q=Petrobras+PETR4` retornou itens relevantes).
- OK "CVM IPE automatizavel" - confirmado: 1.151 Fatos Relevantes em 2026, 191 so em maio, atualizacao same-day.
- DUVIDA "Marketaux cobre B3 com `.SA`" - **nao verificavel sem key**. Doc nao lista B3 explicitamente; padrao Yahoo `PETR4.SA` e o convencional mas nao confirmado empiricamente. Tratar como risco.

### Formato JSON real do brapi quote (capturado, nao inventado)
```json
{"results":[{"symbol":"PETR4","longName":"Petroleo Brasileiro SA Pfd","currency":"BRL",
"regularMarketPrice":44.48,"regularMarketDayHigh":44.75,"regularMarketDayLow":43.87,
"regularMarketChange":-0.47,"regularMarketChangePercent":-1.05,
"regularMarketTime":"2026-05-22T21:30:30.000Z","regularMarketPreviousClose":44.42,
"regularMarketVolume":39610500,"marketCap":613085621299}],
"requestedAt":"2026-05-24T18:20:22.014Z","took":140}
```
- Preco: `results[0].regularMarketPrice`. Variacao: `regularMarketChange` (R$) / `regularMarketChangePercent` (%).
- **Delay:** comparar `regularMarketTime` (timestamp do dado) vs `requestedAt` (agora). No gratis a diferenca reflete os ~15min. Nao ha campo "delay" explicito.
- Multi-ticker: `quote/PETR4,VALE3,ITUB4,MGLU3` num GET so -> economiza quota (1 req).

### Patterns criados no vault
- `patterns/integrations/brapi-b3-cotacao.md` - brapi quote: allowlist de 4 tickers no free, auth via `?token=`, shapes de erro, schema do retorno, calculo de delay.
- `patterns/integrations/fontes-noticias-acoes-b3.md` - RSS PT (InfoMoney/Money Times/Google News) + CVM IPE + Marketaux: URLs verificadas, encoding latin-1, filtro por ticker, schema CSV CVM.
- Linha adicionada em `patterns/_index.md` (secao Integracoes/externals).

## Next steps (o que o PM deve / nao deve assumir na spec)
- [ ] **Assumir:** brapi pago (R$83/mes) se a carteira tiver >4 acoes. Especificar variavel `BRAPI_TOKEN` e auth via query param `?token=`.
- [ ] **Assumir:** parsing RSS deve declarar encoding **latin-1** explicitamente (InfoMoney/CVM nao sao UTF-8) - senao acentos quebram.
- [ ] **Assumir:** associacao noticia->ticker via (a) Money Times tag feed, (b) keyword do nome da empresa + codigo no titulo/`<category>`, (c) Google News query por empresa. Nao ha ticker estruturado no RSS.
- [ ] **Assumir:** CVM IPE = baixar ZIP do ano, descompactar, filtrar `Categoria=="Fato Relevante"` + `Nome_Companhia`, dedup por `Protocolo_Entrega`. `Link_Download` aponta pro RAD (PDF do fato).
- [ ] **Nao assumir:** que Marketaux cobre B3 - validar com key real antes de depender dele. Marcar como fonte secundaria.
- [ ] **Nao assumir:** que `<link>` do Google News e a URL do veiculo - e redirect Google; precisa resolver/seguir pra obter a real.

## Dead-ends & detours
- **Tentei:** WebFetch da doc do Marketaux (`/documentation`) -> **Problema:** HTTP 403 (anti-bot) -> **Virei pra:** bater no endpoint real sem token (confirmou URL + shape de erro `invalid_api_token`) + WebSearch p/ limites do free plan.
- **Tentei:** `grep -P` pra extrair `<item>` do RSS -> **Problema:** locale nao-UTF-8 do ambiente -> **Virei pra:** Python `urllib` + `re.S`, que tambem confirmou encoding latin-1.

## Blockers / questions
- **Marketaux com B3:** sem API key nao da pra confirmar empiricamente se `.SA` funciona nem o sentimento real. QA/dev deve testar com key antes de spec depender dele. -> nao bloqueia (fonte e secundaria).
- **Anthropic + prompt caching:** **nao existe pattern no vault** sobre Claude API / prompt caching. Sinalizado conforme pedido - nao criei agora. Sugiro criar antes da fase de implementacao da analise de noticias (o briefing diario + analise repetida de prompt-base se beneficia muito de caching -> economia de custo).
