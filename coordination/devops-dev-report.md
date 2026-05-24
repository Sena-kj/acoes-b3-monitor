---
status: completed
agent: devops-dev
feature: acoes-b3-monitor
date: 2026-05-24
---

## Summary

- Criados `Dockerfile` (multi-stage, python:3.12-slim, TZ=America/Sao_Paulo, usuario nao-root), `docker-compose.yml` (restart:unless-stopped, volume nomeado b3_data para SQLite, sem portas expostas) e `.dockerignore` correto.
- Criado `.env.example` com todas as 15 vars da spec (TICKERS, BRAPI_TOKEN, TELEGRAM_*, ANTHROPIC_*, BRIEFING_TIME, 4x BUY_PRICE, 4x ALERT_TRIGGER) com comentarios e exemplos dos formatos `price:` e `pct:`.
- Criados `deploy/README.md` (guia VPS Ubuntu), `deploy/deploy.sh` (script de update), e `tests/deploy/test_docker_compose_config.py` (22 testes de validacao de config — todos passando).

## Result

### Arquivos criados

| Arquivo | Descricao |
|---|---|
| `Dockerfile` | Multi-stage builder+runtime. python:3.12-slim. tzdata + TZ=America/Sao_Paulo. pip install --prefix=/install. Usuario nao-root (appuser:1001). CMD python -m acoes_b3_monitor.main |
| `docker-compose.yml` | Service monitor. restart:unless-stopped. env_file:.env. volume b3_data->/app/data. sem ports. healthcheck. limites 256MB RAM |
| `.dockerignore` | Exclui .env*, .git, __pycache__, .venv, *.db, tests/, coordination/, dist/, build/ |
| `.env.example` | 15 vars com comentarios. BRAPI_TOKEN vazio (plano gratis). Exemplos price:42.00 e pct:5 |
| `deploy/README.md` | Guia VPS Ubuntu: instalar Docker, clonar, preencher .env, compose up -d, logs, backup, troubleshooting |
| `deploy/deploy.sh` | Script shell: git pull + docker compose up -d --build |
| `tests/deploy/test_docker_compose_config.py` | 22 testes: compose (restart/env_file/volume/sem-ports/TZ), Dockerfile (python312/tzdata/TZ/no-libgl1-mesa-glx/non-root/multistage/data-dir/entrypoint), .env.example (15 vars/sem-secrets/BRAPI-vazio/formatos), .dockerignore |

### Validacoes executadas

- `docker compose config` — YAML validado, sem erros. Compose resolve todas as vars do .env.example corretamente.
- `uv run pytest tests/deploy/ -v` — 22/22 PASSED.
- `docker build` — Docker daemon nao estava rodando localmente (Docker Desktop parado). Build nao executado. Dockerfile revisado manualmente: sintaxe valida, sem instrucoes problematicas.

### Como testar local (quando Docker Desktop estiver rodando)

```bash
# Validar compose YAML (requer .env existir)
cp .env.example .env   # preencher antes de subir de verdade
docker compose config

# Build da imagem
docker compose build

# Rodar os testes de config
uv run pytest tests/deploy/ -v

# Subir o servico (requer .env preenchido com tokens reais)
docker compose up -d
docker compose logs -f monitor
```

## Deploy checklist

- [x] `.env.example` atualizado com todas as vars novas (15 vars documentadas)
- [x] Variaveis sao 100% runtime — nenhuma e build-time (nao ha NEXT_PUBLIC_* nem build-args)
- [x] `docker compose config` passa local (YAML validado)
- [ ] `docker build` — aguarda Docker Desktop rodando para teste completo (daemon nao disponivel nesta sessao)
- [ ] CI verde no PR — nenhum workflow criado ainda (sem .github/workflows/ no projeto; adicionar se necessario)

## Proximos passos

Acoes que requerem o Kauan (humano):

- [ ] **Preencher .env no VPS** com os tokens reais antes de subir: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, ANTHROPIC_API_KEY, e os precos/gatilhos dos ativos.
- [ ] **Confirmar entrypoint com python-dev**: o CMD atual usa `python -m acoes_b3_monitor.main`. Se python-dev implementar o modulo com funcao `main()` diferente (ex: `create_scheduler()` como loop bloqueante), apenas a linha CMD no Dockerfile precisa mudar. Nenhuma mudanca de logica.
- [ ] **Confirmar DATA_DIR**: o codigo Python (config.py/storage.py) precisa usar `/app/data` como diretorio do SQLite. Se usar outro caminho, o volume precisa ser ajustado. Abri inbox message para python-dev.
- [ ] **Testar build com Docker Desktop rodando**: `docker compose build && docker compose up -d` no ambiente local do Kauan para confirmar que build completo passa antes do deploy no VPS.
- [ ] **CI/CD (opcional)**: sem .github/workflows/ no projeto. Se quiser deploy automatico via GitHub Actions ao fazer push, despachar devops-dev novamente com escopo de "adicionar workflow de CI".

## Dead-ends & detours

- **Tentei:** Dockerfile com dois RUN separados (instalar deps primeiro com pyproject.toml-only, depois instalar app com codigo) — o padrao classico de cache de layers Docker. **Problema:** hatchling (build-backend) precisa do pacote `acoes_b3_monitor/` presente para resolver o sdist durante `pip install .`; rodar com so o pyproject.toml falharia em `pip install .` com "package not found". Esse padrao funciona com Poetry/uv (que tem suporte a `--no-root`), nao com pip/hatchling direto. **Virei pra:** COPY pyproject.toml + acoes_b3_monitor/ juntos, unico RUN pip install. Cache de layer menos granular mas correto.

## Blockers / questions

- **Entrypoint a confirmar**: `python -m acoes_b3_monitor.main` assume que `main.py` e executavel como modulo (`if __name__ == "__main__": main()`). Se python-dev implementar diferente, ajustar CMD. Inbox message criada em `coordination/inbox/devops-to-python-dev.md` com a pergunta.
- **DATA_DIR**: storage.py precisa salvar o SQLite em `/app/data` (onde o volume e montado). Se usar path relativo `./monitor.db`, o arquivo vai para `/app/monitor.db` e NAO sera persistido no volume. Incluido na inbox message.
