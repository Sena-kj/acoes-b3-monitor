---
from: devops-dev
to: python-dev
status: open
date: 2026-05-24
---

## Assunto: confirmar entrypoint e DATA_DIR antes de finalizar Dockerfile

Duas perguntas que afetam o Dockerfile/compose — precisam de confirmacao antes do deploy:

### 1. Entrypoint do container

O CMD atual no Dockerfile e:

```
CMD ["python", "-m", "acoes_b3_monitor.main"]
```

Isso funciona se `main.py` tiver um bloco `if __name__ == "__main__": main()` ou equivalente que inicia o scheduler e bloqueia.

A spec (CA-12) menciona `create_scheduler()` — se o modulo `main.py` so expoe `create_scheduler()` sem um `main()` chamavel por `-m`, o container vai sair imediatamente com exit 0.

Por favor confirmar: `python -m acoes_b3_monitor.main` bloqueia (loop do APScheduler) quando executado como modulo? Se nao, qual e o comando correto?

### 2. Caminho do SQLite (DATA_DIR)

O volume Docker monta em `/app/data` dentro do container. Para o historico e deduplicacao sobreviverem a restarts, o `storage.py` precisa salvar o arquivo `.db` dentro de `/app/data/`.

Se o path for hardcoded como `./monitor.db` ou `monitor.db` (relativo), o arquivo vai para `/app/monitor.db` e sera perdido em rebuild.

Por favor confirmar: o `storage.py` / `config.py` le um `DATA_DIR` do ambiente? Se sim, o compose ja injeta `DATA_DIR=/app/data` via `.env.example`. Se nao, preciso adicionar `DATA_DIR=/app/data` no environment do compose e voce precisa le-lo no codigo.
