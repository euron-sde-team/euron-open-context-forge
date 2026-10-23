"""Background worker: optimization jobs and benchmark runs.

Stateless and safe to run as several replicas: work is claimed with ``FOR UPDATE SKIP
LOCKED`` and leases, so two workers never take the same item. SIGTERM finishes the item
in hand, then exits.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal

from contextforge.benchmark_runs import service as benchmarks
from contextforge.core.config import get_settings
from contextforge.core.container import Container
from contextforge.core.logs import configure_logging
from contextforge.engine.tokenizers import warm_up
from contextforge.jobs import service as jobs

log = logging.getLogger("contextforge.worker")


async def tick(container: Container) -> bool:
    """Process at most one job and one benchmark run. True when anything was done."""
    did_job = await jobs.run_once(container)
    did_bench = await benchmarks.run_once(container)
    return did_job or did_bench


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    warm_up()
    container = Container.build(settings)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    log.info("worker started", extra={"cache": container.kv.backend, "storage": settings.storage})
    try:
        while not stop.is_set():
            try:
                busy = await tick(container)
            except Exception:
                log.exception("worker tick failed")
                busy = False
            if not busy:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), timeout=settings.job_poll_interval_s)
    finally:
        await container.close()
        log.info("worker stopped")
