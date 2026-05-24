---
agent: security-reviewer
feature: acoes-b3-monitor
status: done
date: 2026-05-24
verdict: approved-with-comments
reviewed-commit: ce779a1
---

# Security Review - acoes-b3-monitor

## Summary

APPROVED-WITH-COMMENTS - 0 criticas, 1 alta, 3 medias, 2 baixas.

Contagem: Critica=0, Alta=1, Media=3, Baixa=2.

Nenhuma vulnerabilidade bloqueia deploy imediatamente. O achado Alta (SSRF sem
validacao de host no resolver do Google News) deve ser corrigido antes de qualquer
expansao de fontes de noticias. Achados Medios sao mitiaveis com patches pequenos.

---

## Result

### [ALTA] SSRF na resolucao de redirect do Google News

Arquivo: news_collector.py:179-194

Descricao:
A funcao _resolve_google_redirect segue redirects via follow_redirects=True sem
validar host/esquema da URL final. O cliente do fetch_news usa follow_redirects=False
(correto para feed RSS) mas dentro de _resolve_google_redirect e chamado com
follow_redirects=True sem qualquer verificacao do hostname/esquema da URL resultante.

Se o feed incluir redirect para http://169.254.169.254/ ou IPs RFC1918 (poisoning
do feed ou bug futuro), o codigo fara a requisicao sem barreira. O mesmo AsyncClient
compartilhado e passado para _resolve_google_redirect - headers de auth adicionados
no futuro ao cliente compartilhado vazarao para qualquer host resolvido (ver
pitfalls/httpx-custom-header-forwarded-on-redirect.md).

Evidencia:
  news_collector.py:187 - client.head(url, follow_redirects=True, timeout=5.0)
  news_collector.py:192 - client.get(url, follow_redirects=True, timeout=5.0)

Reproducao hipotetica: Feed RSS retorna link para
http://169.254.169.254/latest/meta-data/iam/security-credentials/ ->
codigo faz HEAD/GET para o IMDS do VPS.

Fix sugerido: Apos resolver o redirect, validar que final_url tem scheme https
e hostname nao e IP privado/loopback (ipaddress + denylist RFC1918). Ver padrao
em pitfalls/ssrf-media-ingestion.md. Criar _validate_resolved_url(url: str) -> None
e chamar antes de retornar. Usar cliente httpx separado (sem headers compartilhados)
para o resolve.

---

### [MEDIA] Token Telegram logado indiretamente no erro 400

Arquivo: notifier.py:151

Descricao:
No path de erro HTTP 400, o codigo loga o payload completo incluindo chat_id e
texto da mensagem. O TELEGRAM_BOT_TOKEN esta no path da URL da requisicao e pode
aparecer nos logs se logging de nivel DEBUG do httpx for ativado em producao.

Evidencia:
  notifier.py:132 - url = TELEGRAM_API_BASE + /bot{token}/sendMessage
  notifier.py:151 - logger.error("Telegram 400: %s - payload: %s", data, payload)

Fix sugerido: Remover payload do log de erro 400, logar apenas data (a resposta
da API). Se logs DEBUG do httpx forem ativados, mascarar o token na URL.

---

### [MEDIA] Ausencia de validacao de tamanho e zip-slip no ZIP da CVM

Arquivo: news_collector.py:259-331

Descricao:
O ZIP da CVM e descompactado em memoria sem verificar: (a) tamanho antes de baixar
via Content-Length header, (b) tamanho descompactado antes de ler, (c) path dos
arquivos no ZIP (zip-slip: ../../etc/cron.d/backdoor).
CVM e fonte confiavel, mas DNS/BGP spoofing poderia entregar ZIP malicioso.
O limite de 256MB RAM do container mitiga zip bomb mas nao zip-slip.

Evidencia:
  news_collector.py:269 - zipfile.ZipFile(io.BytesIO(resp.content))
  news_collector.py:275 - zf.open(csv_names[0]) sem checar path

Fix sugerido:
  (1) Verificar Content-Length antes de baixar (rejeitar se > 50MB)
  (2) Validar csv_names[0] nao contem .. nem path absoluto
  (3) Verificar file_size descompactado antes de f.read() (rejeitar se > 100MB)

---

### [MEDIA] feedparser sem defusedxml explicito

Arquivo: news_collector.py:95,148,211

Descricao:
O feedparser 6.x usa xml.etree.ElementTree sem garantia documentada de protecao
total contra XXE nem Billion Laughs em todos os parsers de fallback. O vetor
requer uma fonte RSS servindo XML malicioso (supply-chain ou comprometimento).

Evidencia:
  pyproject.toml:13 - feedparser>=6.0
  news_collector.py:95 - feedparser.parse(xml_text)

Fix sugerido: Instalar defusedxml e confirmar que feedparser 6.x o usa, ou
adicionar teste de regressao com XML malicioso (entidades externas e billion laughs).

---

### [BAIXA] BRAPI_TOKEN enviado como query param

Arquivo: quote_collector.py:52-54

Token da brapi enviado como ?token=<value> (query param). Query params aparecem em
logs de acesso de servidor e proxy/CDN. E pratica menos segura que Authorization Bearer.
Nao ha controle do app - a API da brapi exige query param.

Evidencia: quote_collector.py:52-54 - params[token] = self._token
Observacao: Registrar como known risk ate que brapi ofeca autenticacao por header.

---

### [BAIXA] Ausencia de validacao de presenca de secrets na inicializacao

Arquivo: config.py:82-84

Os campos telegram_bot_token, telegram_chat_id e anthropic_api_key tem default=""
(string vazia) sem validators de presenca. O servico sobe silenciosamente com
secrets ausentes e so falha na primeira chamada real.

Evidencia: config.py:82-84 - default="" sem @field_validator de presenca.
Fix sugerido: Adicionar validators que levantam ValueError se o valor for vazio (fail-fast).

---

## Deps vulneraveis

Auditoria manual das deps em pyproject.toml - nenhuma CVE ativa identificada:
  httpx>=0.27, feedparser>=6.0, apscheduler>=3.10, pydantic>=2.7,
  anthropic>=0.28, aiosqlite>=0.20.

Recomendado: rodar pip-audit contra o uv.lock para confirmar versoes exatas.

---

## Segredos no repositorio

Conferido via git ls-files: nenhum .env real rastreado. .gitignore e .dockerignore
cobrem .env e .env.* corretamente. .env.example contem apenas placeholders.
Grep por AKIA, sk-, ghp_, xox[bp], api_key hardcoded: 0 matches no codigo-fonte.

---

## Achados positivos

- Container roda como usuario nao-root (appuser uid 1001) - correto.
- Imagem usa python:3.12-slim com build multi-stage (superficie minima).
- Todas as queries SQLite usam parametros posicionais - sem SQL injection.
- Secrets carregados exclusivamente via pydantic-settings do .env - nao hardcoded.
- HTTPS forcado em todas as chamadas externas (Telegram, Anthropic, brapi, CVM, RSS).
- System prompt do Claude tem fronteiras explicitas contra previsao de preco/recomendacao.
- follow_redirects=False no cliente principal do fetch_news.

---

## Next steps

1 (Alta):  Adicionar _validate_resolved_url em _resolve_google_redirect    -> python-dev
2 (Media): Remover payload do logger.error em notifier.py:151              -> python-dev
3 (Media): Validacao tamanho + path-traversal no ZIP da CVM                -> python-dev
4 (Media): Teste de XML malicioso para protecao XXE feedparser             -> python-dev
5 (Baixa): Validators de presenca em config.py para tokens obrigatorios    -> python-dev
6 (Info):  Rodar pip-audit contra o uv.lock                               -> devops-dev

Severidade Alta nao bloqueia deploy atual mas bloqueia adicao de novas fontes
de URL externas sem validacao implementada.

## Blockers / questions

Nenhum - todos os achados tem fix claro sem decisao de produto.
