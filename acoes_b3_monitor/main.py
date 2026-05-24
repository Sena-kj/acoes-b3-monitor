"""
main.py — Entrypoint do acoes-b3-monitor.

Funcoes exportadas:
  create_scheduler() -> AsyncIOScheduler   — para smoke gate e testes
  main()                                   — loop principal (asyncio.run)

Uso:
  uv run python -m acoes_b3_monitor.main
  uv run acoes-b3-monitor
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)

logger = logging.getLogger(__name__)


class _SafeScheduler:
    """
    Wrapper em torno do AsyncIOScheduler que torna shutdown() seguro mesmo
    quando o scheduler ainda nao foi iniciado (SchedulerNotRunningError).
    """

    def __init__(self, inner):
        self._inner = inner

    def shutdown(self, wait: bool = True) -> None:
        from apscheduler.schedulers.base import STATE_STOPPED
        try:
            self._inner.shutdown(wait=wait)
        except Exception:
            pass  # silencioso se nao estava rodando

    def start(self) -> None:
        self._inner.start()

    def get_jobs(self):
        return self._inner.get_jobs()

    @property
    def running(self) -> bool:
        return self._inner.running


def create_scheduler():
    """
    Cria e retorna AsyncIOScheduler configurado (nao iniciado).

    Smoke gate:
      python -c "from acoes_b3_monitor.main import create_scheduler; s=create_scheduler(); s.shutdown(wait=False)"
    """
    from .scheduler import create_scheduler as _create
    return _SafeScheduler(_create())


async def _run() -> None:
    """Loop principal: inicia scheduler e aguarda SIGINT/SIGTERM."""
    from .config import get_db_path, get_settings
    from .storage import init_db

    settings = get_settings()
    db_path = get_db_path()

    logger.info("acoes-b3-monitor iniciando. Tickers: %s", settings.tickers)

    # Inicializa o banco antes de subir o scheduler
    await init_db(db_path)
    logger.info("Storage inicializado em %s", db_path)

    scheduler = create_scheduler(settings, db_path)
    scheduler.start()
    logger.info("Scheduler iniciado com %d jobs", len(scheduler.get_jobs()))

    stop_event = asyncio.Event()

    def _handle_signal(*_) -> None:
        logger.info("Sinal de parada recebido. Encerrando...")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _handle_signal)
        except (NotImplementedError, RuntimeError):
            # Windows nao suporta add_signal_handler no asyncio; fallback para KeyboardInterrupt
            pass

    try:
        await stop_event.wait()
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        scheduler.shutdown(wait=False)
        logger.info("acoes-b3-monitor encerrado.")


def main() -> None:
    """Entrypoint CLI (pyproject.toml scripts)."""
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        sys.exit(0)


# Permite: python -m acoes_b3_monitor.main
if __name__ == "__main__":
    main()
