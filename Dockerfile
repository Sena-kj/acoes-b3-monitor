# ============================================================
# Stage 1 — builder
# Instala dependencias e empacota o projeto usando pip.
# ============================================================
FROM python:3.12-slim AS builder

# Evita prompts interativos durante apt-get
ENV DEBIAN_FRONTEND=noninteractive

# Dependencias de build minimas
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copia o pyproject.toml e o pacote de uma vez.
# Nota: cache layer de deps e limitado aqui porque hatchling precisa do pacote
# para instalar. Se quiser cache mais granular, teria que usar uv (pip suporta
# apenas `pip install <deps-list>` sem o pacote em si).
COPY pyproject.toml ./
COPY acoes_b3_monitor/ ./acoes_b3_monitor/

# Instala o pacote e todas as deps de runtime em /install
# --no-cache-dir: nao guarda cache no layer da imagem final
# --prefix=/install: permite COPY seletivo para o stage runtime
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir --prefix=/install .

# ============================================================
# Stage 2 — runtime
# Imagem minima com apenas o necessario para rodar.
# ============================================================
FROM python:3.12-slim AS runtime

# NOTA: Este servico e puro Python/HTTP — nao usa OpenCV nem libgl1.
#       Se no futuro adicionar processamento de imagem, usar libgl1 (NAO libgl1-mesa-glx
#       — removido em Debian 13 trixie; ver pitfall debian-trixie-libgl1-mesa-glx-removed).
#
# tzdata: obrigatorio para America/Sao_Paulo no APScheduler.
# ca-certificates: TLS para chamadas externas (brapi, Telegram, Anthropic, CVM).
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        tzdata \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Timezone critico: scheduler usa horario do pregao BRT (09:45-17:30)
ENV TZ=America/Sao_Paulo
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# Copia pacotes instalados do builder para o site-packages do runtime
COPY --from=builder /install /usr/local

# Copia codigo fonte
COPY --from=builder /app/acoes_b3_monitor /app/acoes_b3_monitor
COPY --from=builder /app/pyproject.toml /app/pyproject.toml

WORKDIR /app

# Variaveis de ambiente de runtime (NAO secrets — esses vem do .env injetado pelo compose/plataforma)
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app

# Diretorio de dados persistentes (SQLite)
# O volume do compose monta em /app/data; o codigo deve usar DATA_DIR=/app/data
RUN mkdir -p /app/data

# Usuario nao-root para seguranca
RUN groupadd --gid 1001 appgroup \
    && useradd --uid 1001 --gid appgroup --no-create-home appuser \
    && chown -R appuser:appgroup /app
USER appuser

# Entrypoint: modulo main do pacote
# Confirmado com python-dev: pyproject.toml declara entrypoint acoes_b3_monitor.main:main
# Se o entrypoint mudar, alterar apenas esta linha.
CMD ["python", "-m", "acoes_b3_monitor.main"]
