"""
Testes de validacao da configuracao de deploy (sem Docker em execucao).

Estes testes verificam:
- docker-compose.yml tem campos criticos (volume, restart, env_file)
- .env.example contem todas as vars esperadas
- Dockerfile tem instrucoes criticas (TZ, tzdata, USER nao-root)

Rodar: pytest tests/deploy/ -v
(nao requer Docker instalado)
"""

import pathlib
import re

PROJECT_ROOT = pathlib.Path(__file__).parent.parent.parent


def read(filename: str) -> str:
    return (PROJECT_ROOT / filename).read_text(encoding="utf-8")


class TestDockerCompose:
    def test_restart_policy(self):
        content = read("docker-compose.yml")
        assert "restart: unless-stopped" in content, "Faltou restart: unless-stopped"

    def test_env_file_declared(self):
        content = read("docker-compose.yml")
        assert "env_file:" in content, "Faltou env_file no compose"

    def test_named_volume_exists(self):
        content = read("docker-compose.yml")
        assert "b3_data:" in content, "Faltou volume nomeado b3_data"
        assert "volumes:" in content

    def test_no_ports_exposed(self):
        content = read("docker-compose.yml")
        # Servico nao e web server — nao deve expor portas
        assert "ports:" not in content, "Compose nao deve expor portas (daemon puro)"

    def test_timezone_env(self):
        content = read("docker-compose.yml")
        assert "America/Sao_Paulo" in content, "TZ America/Sao_Paulo deve estar no compose"


class TestDockerfile:
    def test_python312_base(self):
        content = read("Dockerfile")
        assert "python:3.12-slim" in content

    def test_tzdata_installed(self):
        content = read("Dockerfile")
        assert "tzdata" in content, "tzdata obrigatorio para America/Sao_Paulo"

    def test_timezone_set(self):
        content = read("Dockerfile")
        assert "TZ=America/Sao_Paulo" in content

    def test_no_libgl1_mesa_glx_in_apt_install(self):
        # Pitfall: libgl1-mesa-glx removido no Debian 13 trixie (pode aparecer em comentario, nunca em apt-get install)
        content = read("Dockerfile")
        apt_lines = [
            line for line in content.splitlines()
            if "apt-get install" in line or (
                # captura linhas de continuacao de um RUN apt-get install
                line.strip().startswith(("lib", "python", "curl", "build", "ca-", "tz"))
                and not line.strip().startswith("#")
            )
        ]
        apt_block = "\n".join(apt_lines)
        assert "libgl1-mesa-glx" not in apt_block, (
            "libgl1-mesa-glx NAO deve ser instalado (removido no Debian 13 trixie). Use libgl1."
        )

    def test_non_root_user(self):
        content = read("Dockerfile")
        assert "USER appuser" in content, "Container deve rodar como usuario nao-root"

    def test_multistage_build(self):
        content = read("Dockerfile")
        stages = re.findall(r"^FROM .+ AS \w+", content, re.MULTILINE)
        assert len(stages) >= 2, "Dockerfile deve ter multi-stage build (builder + runtime)"

    def test_data_dir_created(self):
        content = read("Dockerfile")
        assert "/app/data" in content, "Diretorio /app/data deve ser criado no Dockerfile"

    def test_entrypoint_references_package(self):
        content = read("Dockerfile")
        assert "acoes_b3_monitor.main" in content, "CMD deve referenciar o modulo main"


class TestEnvExample:
    REQUIRED_VARS = [
        "TICKERS",
        "BRAPI_TOKEN",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_MODEL",
        "BRIEFING_TIME",
        "PETR4_BUY_PRICE",
        "PETR4_ALERT_TRIGGER",
        "VALE3_BUY_PRICE",
        "VALE3_ALERT_TRIGGER",
        "ITUB4_BUY_PRICE",
        "ITUB4_ALERT_TRIGGER",
        "MGLU3_BUY_PRICE",
        "MGLU3_ALERT_TRIGGER",
    ]

    def test_all_required_vars_present(self):
        content = read(".env.example")
        missing = [v for v in self.REQUIRED_VARS if v not in content]
        assert not missing, f"Vars faltando no .env.example: {missing}"

    def test_no_real_secrets(self):
        content = read(".env.example")
        # Nao deve ter tokens reais — so placeholders
        assert "sk-ant-" not in content, "API key real no .env.example"
        assert "bot" not in content.lower().split("=")[0] if "TOKEN=" in content else True

    def test_brapi_token_empty_default(self):
        content = read(".env.example")
        # BRAPI_TOKEN deve estar vazio por padrao (plano gratis)
        assert "BRAPI_TOKEN=" in content
        line = [l for l in content.splitlines() if l.startswith("BRAPI_TOKEN=")][0]
        assert line.strip() == "BRAPI_TOKEN=", "BRAPI_TOKEN deve ser vazio no .env.example"

    def test_trigger_formats_documented(self):
        content = read(".env.example")
        assert "price:" in content, "Formato price: deve aparecer no .env.example"
        assert "pct:" in content, "Formato pct: deve aparecer no .env.example"


class TestDockerignore:
    def test_env_excluded(self):
        content = read(".dockerignore")
        assert ".env" in content

    def test_git_excluded(self):
        content = read(".dockerignore")
        assert ".git" in content

    def test_pycache_excluded(self):
        content = read(".dockerignore")
        assert "__pycache__" in content

    def test_tests_excluded(self):
        content = read(".dockerignore")
        assert "tests/" in content

    def test_db_files_excluded(self):
        content = read(".dockerignore")
        assert "*.db" in content or "*.sqlite" in content
