---
status: completed
agent: pm
feature: acoes-b3-monitor
date: 2026-05-24
---

# Spec — acoes-b3-monitor MVP

## Problema

Investidor pessoa física que acompanha B3 não tem como receber alertas automáticos no celular quando um ativo da carteira cruza um preço-gatilho, nem um resumo diário com notícias relevantes e análise de sentimento das empresas monitoradas — hoje ele precisa abrir aplicativo ou site manualmente.

## User stories

1. Como investidor, quero receber uma mensagem no Telegram quando o preço de um ativo cair abaixo do meu gatilho, para decidir se compro mais.
2. Como investidor, quero receber uma mensagem no Telegram quando uma notícia relevante (fato relevante CVM ou RSS PT) for detectada sobre um ativo da minha carteira, junto com análise de sentimento da Claude, para decidir se ajo.
3. Como investidor, quero receber um briefing diário da minha carteira todo dia às 8h BRT, com cotação de abertura, variação percentual e resumo das notícias das últimas 24h por ativo.
4. Como investidor, quero configurar: quais 4 ativos monitorar, meu preço de compra por ativo, e o gatilho de alerta (preço absoluto ou % abaixo do preço de compra), sem precisar editar código.

## Fluxo de UX (mensagens Telegram)

### Alerta de preço
```
[ALERTA PETR4] Preço atual: R$ 41,20
Gatilho atingido: R$ 42,00 (preço de compra R$ 45,00 - 6,7% abaixo)
Cotação com delay ~15min (brapi free). Horário do dado: 10:32 BRT
```

### Alerta de notícia
```
[NOTÍCIA VALE3] Fato Relevante CVM — 24/05/2026 09:14
"Vale anuncia resultado operacional do 1T26"
Fonte: CVM IPE | Link: https://...

Análise Claude:
Sentimento: NEUTRO
Contexto: Relatório operacional trimestral de rotina. Sem impacto imediato esperado. Produção de minério dentro do guidance.
```

### Briefing diário (08:00 BRT)
```
Bom dia! Carteira B3 — 24/05/2026

PETR4  R$ 44,48  -1,05% hoje | compra: R$ 45,00 (-1,2%)
VALE3  R$ 62,10  +0,3% hoje  | compra: R$ 60,00 (+3,5%)
ITUB4  R$ 35,20  -0,5% hoje  | compra: R$ 34,00 (+3,5%)
MGLU3  R$ 12,50  +1,2% hoje  | compra: R$ 15,00 (-16,7%)

Notícias das últimas 24h:
• PETR4: 3 notícias — sentimento médio: NEUTRO
• VALE3: 1 fato relevante CVM — sentimento: POSITIVO
• ITUB4: sem notícias
• MGLU3: 2 notícias — sentimento médio: NEGATIVO

[Resumo Claude em 3 linhas sobre o dia]
```

## Módulos e fronteiras

```
services/
  quote_collector.py      — fetch brapi, retorna Quote; abstrai provider
  news_collector.py       — fetch RSS + CVM IPE, retorna NewsItem[]
  alert_engine.py         — compara Quote vs AlertRule, emite AlertEvent
  news_analyzer.py        — Claude API: NewsItem -> NewsAnalysis
  notifier.py             — Telegram bot: envia texto formatado
  briefing_builder.py     — agrega Quote[] + NewsAnalysis[] -> DailyBriefing
  scheduler.py            — APScheduler: agenda polling e briefing
  storage.py              — SQLite: persiste Quote, NewsItem, AlertEvent, cache
config.py                 — lê .env, expõe Settings (Pydantic BaseSettings)
main.py                   — entrypoint: instancia scheduler, sobe o loop
```

Cada módulo expõe uma função principal testável de forma isolada. Nenhum módulo importa de outro exceto pelo fluxo definido abaixo.

### Fluxo de dados

```
scheduler
  ├─ a cada 5min (09:45–17:30 BRT dias úteis)
  │    quote_collector → Quote[] → alert_engine → AlertEvent[] → notifier
  │
  ├─ a cada 30min (00:00–23:59 todos os dias)
  │    news_collector → NewsItem[] → news_analyzer → NewsAnalysis[] → notifier
  │    (notifica só se ticker monitorado e notícia nova — dedup por guid/Protocolo_Entrega)
  │
  └─ diariamente 08:00 BRT
       quote_collector + news_collector + briefing_builder → DailyBriefing → notifier
```

## Configuração do usuário (via .env)

```
TICKERS=PETR4,VALE3,ITUB4,MGLU3          # exatamente 4 no free; separados por vírgula
BRAPI_TOKEN=                              # vazio = free (só 4 tickers acima)
TELEGRAM_BOT_TOKEN=<bot_token>
TELEGRAM_CHAT_ID=<chat_id>
ANTHROPIC_API_KEY=<key>
BRIEFING_TIME=08:00                       # HH:MM BRT

# Por ativo — formato: <TICKER>_BUY_PRICE e <TICKER>_ALERT_TRIGGER
PETR4_BUY_PRICE=45.00
PETR4_ALERT_TRIGGER=price:42.00          # gatilho absoluto
VALE3_BUY_PRICE=60.00
VALE3_ALERT_TRIGGER=pct:5               # 5% abaixo do preço de compra
ITUB4_BUY_PRICE=34.00
ITUB4_ALERT_TRIGGER=price:33.00
MGLU3_BUY_PRICE=15.00
MGLU3_ALERT_TRIGGER=pct:10
```

Formato de `ALERT_TRIGGER`:
- `price:<valor>` — alerta quando `regularMarketPrice <= valor`
- `pct:<n>` — alerta quando `regularMarketPrice <= buy_price * (1 - n/100)`

## Agendamento

| Job | Frequência | Condição |
|---|---|---|
| Polling de cotação | A cada 5 min | Somente seg–sex, 09:45–17:30 BRT |
| Coleta de notícias | A cada 30 min | Sempre (notícias chegam fora do pregão) |
| Briefing diário | 1x/dia no horário configurado | Sempre |
| Download CVM IPE | 1x/dia às 06:00 BRT | Baixa o ZIP do ano corrente |

Fora do horário do pregão, polling de cotação não roda (economiza quota brapi).

## Critérios de aceite (binários — testáveis)

### CA-01: Cotação coletada
Dado `TICKERS=PETR4,VALE3,ITUB4,MGLU3` e `BRAPI_TOKEN` vazio,
`quote_collector.fetch_quotes()` retorna uma lista com exatamente 4 objetos `Quote`,
cada um com `symbol`, `price > 0`, `change_pct` (float), `market_time` (datetime com tzinfo UTC) e `fetched_at` (datetime).

### CA-02: Delay calculado e logado
`Quote.delay_minutes` = `(fetched_at - market_time).total_seconds() / 60`. Log em INFO deve conter `"delay=<N>min"` para cada ticker.

### CA-03: Alerta por preço absoluto dispara
Dado `Quote(symbol="PETR4", price=41.20)` e `AlertRule(ticker="PETR4", trigger_type="price", trigger_value=42.00)`,
`alert_engine.evaluate(quotes, rules)` retorna uma lista com 1 `AlertEvent` com `ticker="PETR4"` e `trigger_fired=True`.

### CA-04: Alerta por % dispara
Dado `Quote(symbol="MGLU3", price=13.49)`, `AlertRule(ticker="MGLU3", trigger_type="pct", trigger_value=10, buy_price=15.00)` (gatilho em 13.50),
`alert_engine.evaluate` retorna 1 `AlertEvent`.

### CA-05: Alerta não dispara fora do gatilho
Dado `Quote(symbol="VALE3", price=62.00)` e `AlertRule(ticker="VALE3", trigger_type="price", trigger_value=55.00)`,
`alert_engine.evaluate` retorna lista vazia.

### CA-06: Deduplicação de alertas
Se `AlertEvent` para mesmo `ticker` já existe em `storage` com `fired_at` nos últimos 60 minutos, `alert_engine` NÃO emite novo `AlertEvent` (evita spam).

### CA-07: Notícia coletada em PT
`news_collector.fetch_news(["PETR4"])` retorna pelo menos 1 `NewsItem` com `source` em `["infomoney", "moneytimes", "google_news", "cvm_ipe"]`, `title` em UTF-8 sem mojibake (campos com acento corretos), e `published_at` como `datetime` válido.

### CA-08: Deduplicação de notícias
Dois fetches consecutivos do mesmo RSS não dobram os itens no DB. `NewsItem.guid` (para RSS) ou `NewsItem.cvm_protocolo` (para CVM) é UNIQUE no storage.

### CA-09: Análise coerente pelo Claude
Dado `NewsItem(title="Vale anuncia paralisação emergencial em mina MG", body="...")`,
`news_analyzer.analyze(item)` retorna `NewsAnalysis` com `sentiment` em `{"POSITIVO","NEUTRO","NEGATIVO"}` e `summary` com 1–4 frases (string não vazia).
A análise NÃO contém previsão de preço, ganho ou perda financeira (verificação manual de QA).

### CA-10: Briefing diário enviado
Às 08:00 BRT (ou na invocação manual `briefing_builder.build()`),
`DailyBriefing` contém: `quotes[]` com todos os tickers configurados, `news_by_ticker` (dict ticker → `NewsAnalysis[]` das últimas 24h), `summary` (string 1–3 frases gerada pelo Claude). `notifier.send_briefing(briefing)` retorna sem erro e a mensagem chega no Telegram configurado.

### CA-11: Notificação Telegram entregue
`notifier.send_message(text)` faz POST para `https://api.telegram.org/bot<TOKEN>/sendMessage` e retorna sem exceção quando `TELEGRAM_BOT_TOKEN` e `TELEGRAM_CHAT_ID` válidos.

### CA-12: Smoke import + invocação
`python -c "from acoes_b3_monitor.main import create_scheduler; s = create_scheduler(); s.shutdown(wait=False)"` sai com código 0 e sem exceção.

## Fronteira dura: o que a análise Claude NÃO faz

- NÃO prevê preço-alvo nem movimento futuro de cotação.
- NÃO diz "compre", "venda" ou "recomendo".
- NÃO calcula rentabilidade esperada nem ganho/perda.
- Faz APENAS: classificação de sentimento (POSITIVO/NEUTRO/NEGATIVO) + resumo contextual da notícia em até 4 frases.

Essa fronteira deve ser reforçada no system prompt do `news_analyzer` com instrução explícita.

## Fora de escopo (MVP)

- Interface web ou dashboard.
- Suporte a mais de 4 tickers sem `BRAPI_TOKEN` pago.
- Análise técnica (RSI, médias móveis, candles).
- Múltiplos usuários / multitenancy.
- Autenticação ou painel de configuração via Telegram bot commands.
- Marketaux como fonte primária (secundária, opcional, não implementar no MVP).
- Histórico/gráficos de preço.
- Backtesting de alertas.

## Métricas de sucesso

- Alerta de preço chega no Telegram em até 10 minutos após gatilho ser atingido (dado o delay ~15min do brapi free).
- Briefing diário enviado todos os dias úteis antes das 08:10 BRT.
- Zero notícias com texto mojibake (acentos corretos) nos primeiros 7 dias.
- Menos de 1 alerta duplicado por semana (deduplicação funcionando).
