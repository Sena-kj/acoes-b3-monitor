"""
Testes CA-12 — smoke gate de main.create_scheduler().

CA-12: create_scheduler() e invocavel e scheduler.shutdown(wait=False) sai sem excecao.
"""

from __future__ import annotations

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler


def test_ca12_create_scheduler_returns_scheduler(settings) -> None:
    """CA-12: create_scheduler() retorna objeto com interface de scheduler sem lancar excecao."""
    from acoes_b3_monitor.scheduler import create_scheduler

    scheduler = create_scheduler(settings=settings, db_path=":memory:")
    assert isinstance(scheduler, AsyncIOScheduler)
    # Nao iniciado ainda
    assert not scheduler.running


def test_ca12_scheduler_has_all_jobs(settings) -> None:
    """CA-12: Scheduler deve ter os 4 jobs configurados."""
    from acoes_b3_monitor.scheduler import create_scheduler

    scheduler = create_scheduler(settings=settings, db_path=":memory:")
    job_ids = {job.id for job in scheduler.get_jobs()}

    assert "quote_poll" in job_ids, "Job quote_poll ausente"
    assert "news_fetch" in job_ids, "Job news_fetch ausente"
    assert "briefing" in job_ids, "Job briefing ausente"
    assert "cvm_download" in job_ids, "Job cvm_download ausente"


def test_ca12_create_scheduler_shutdown_no_error(settings) -> None:
    """CA-12: Shutdown sem start nao deve lancar excecao (via wrapper _SafeScheduler)."""
    from acoes_b3_monitor.main import create_scheduler

    # main.create_scheduler() retorna _SafeScheduler que suprime SchedulerNotRunningError
    scheduler = create_scheduler()
    scheduler.shutdown(wait=False)  # nao deve lancar


def test_ca12_main_create_scheduler_importable() -> None:
    """CA-12: from acoes_b3_monitor.main import create_scheduler funciona."""
    from acoes_b3_monitor.main import create_scheduler as main_create

    # Verifica que e callable
    assert callable(main_create)


def test_ca12_smoke_gate_full() -> None:
    """
    CA-12: Smoke gate completo.
    Equivalente a: python -c "from acoes_b3_monitor.main import create_scheduler; s=create_scheduler(); s.shutdown(wait=False)"
    """
    from acoes_b3_monitor.main import create_scheduler

    s = create_scheduler()
    s.shutdown(wait=False)
    # Se chegou aqui, exit code seria 0
