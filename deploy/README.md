# Deploy — VPS Ubuntu

Guia minimo para subir o acoes-b3-monitor num VPS Ubuntu 22.04+ limpo.

## Pre-requisitos

- VPS com Ubuntu 22.04+ (1 vCPU / 512 MB RAM e suficiente)
- Acesso SSH com sudo

## 1. Instalar Docker

```bash
# Instala Docker Engine + Compose plugin oficiais
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
newgrp docker          # ou sair e entrar novamente na sessao SSH
docker --version       # deve mostrar Docker 24+
docker compose version # deve mostrar Compose 2+
```

## 2. Clonar o repositorio

```bash
git clone <URL_DO_REPOSITORIO> acoes-b3-monitor
cd acoes-b3-monitor
```

## 3. Configurar o .env

```bash
cp .env.example .env
nano .env   # ou vim, vi, etc.
```

Preencha obrigatoriamente:
- `TELEGRAM_BOT_TOKEN` — token do bot criado com @BotFather
- `TELEGRAM_CHAT_ID` — seu chat ID (instrucoes no .env.example)
- `ANTHROPIC_API_KEY` — chave da Anthropic Console
- Os preco de compra (`*_BUY_PRICE`) e gatilhos (`*_ALERT_TRIGGER`) de cada ativo

## 4. Subir o servico

```bash
docker compose up -d --build
```

O primeiro build leva ~2-3 minutos (baixa imagem base + instala deps Python).
Nas proximas vezes, o cache acelera para ~30s.

## 5. Verificar logs

```bash
# Acompanhar logs em tempo real
docker compose logs -f monitor

# Ultimas 100 linhas
docker compose logs --tail=100 monitor

# Verificar status do container
docker compose ps
```

## 6. Gerenciar o servico

```bash
# Parar (sem remover dados)
docker compose stop

# Reiniciar
docker compose restart monitor

# Atualizar codigo (pull + rebuild + restart)
git pull
docker compose up -d --build

# Parar e remover container (dados SQLite ficam no volume)
docker compose down

# CUIDADO: isto apaga o volume com o SQLite (historico + dedup)
docker compose down -v
```

## 7. Backup do SQLite

```bash
# Cria backup em ./backup/b3_data.tar.gz
mkdir -p backup
docker run --rm \
  -v acoes-b3-monitor_b3_data:/data \
  -v $(pwd)/backup:/backup \
  alpine tar czf /backup/b3_data_$(date +%Y%m%d).tar.gz /data
```

## Troubleshooting

**Container reiniciando repetidamente**
```bash
docker compose logs --tail=50 monitor
# Procurar: erro de variavel de ambiente faltando, falha de conexao, etc.
```

**Alterei o .env mas o container continua com valor antigo**
```bash
docker compose up -d   # Basta — compose recria o container com o novo .env
# (sem --build se o codigo nao mudou)
```

**Quero ver o banco SQLite**
```bash
docker compose exec monitor ls /app/data/
docker compose exec monitor python -c "
import sqlite3, pathlib
db = pathlib.Path('/app/data')
print(list(db.iterdir()))
"
```

**Verificar se o scheduler esta agendado corretamente**
```bash
docker compose logs monitor | grep -i "scheduler\|job\|scheduled"
```

## Notas de seguranca

- O container roda como usuario `appuser` (uid 1001), nao root.
- Nenhuma porta e exposta externamente (sem `ports:` no compose).
- O `.env` nunca deve ser commitado — ja esta no `.gitignore`.
- Para atualizar secrets: editar `.env` no VPS e rodar `docker compose up -d`.
