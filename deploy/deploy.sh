#!/usr/bin/env bash
# deploy.sh — atualiza o acoes-b3-monitor no VPS a partir do repositorio git
# Uso: bash deploy.sh
# Pre-requisito: .env ja configurado no diretorio do projeto

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "[deploy] Entrando em $PROJECT_DIR"
cd "$PROJECT_DIR"

# Verifica que .env existe (nao commita secrets)
if [[ ! -f ".env" ]]; then
    echo "[deploy] ERRO: .env nao encontrado. Copie .env.example e preencha."
    exit 1
fi

echo "[deploy] Atualizando codigo..."
git pull --ff-only

echo "[deploy] Build + restart do container..."
docker compose up -d --build --remove-orphans

echo "[deploy] Status:"
docker compose ps

echo "[deploy] Ultimas linhas de log:"
docker compose logs --tail=20 monitor

echo "[deploy] Concluido. Acompanhe os logs com: docker compose logs -f monitor"
