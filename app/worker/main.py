from __future__ import annotations

import argparse
import asyncio
import logging
import time

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import dispose_engine
from app.modules.notifications.delivery import close_delivery_clients
from app.worker.jobs import run_once


async def worker_loop(interval_minutes: int, settings=None) -> None:
    resolved_settings = settings or get_settings()
    logger = logging.getLogger("worker")
    while True:
        start = time.monotonic()
        try:
            stats = await run_once(settings=resolved_settings)
        except Exception:
            logger.exception("Worker cycle failed")
            await asyncio.sleep(resolved_settings.worker_failure_backoff_seconds)
            continue

        logger.info(
            "Worker cycle completed: evaluated_alerts=%s created_triggers=%s delivered_notifications=%s failed_notifications=%s",
            stats.evaluated_alerts,
            stats.created_triggers,
            stats.delivered_notifications,
            stats.failed_notifications,
        )
        elapsed = time.monotonic() - start
        sleep_seconds = max(interval_minutes * 60 - elapsed, 0)
        await asyncio.sleep(sleep_seconds)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Climate alerts worker")
    parser.add_argument("--interval-minutes", type=int, default=None, help="Loop interval in minutes")
    parser.add_argument("--run-once", action="store_true", help="Run a single worker cycle and exit")
    return parser.parse_args()


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    args = parse_args()
    interval_minutes = args.interval_minutes or settings.worker_interval_minutes
    if interval_minutes < 1:
        raise SystemExit("--interval-minutes must be >= 1")

    async def runner() -> None:
        try:
            if args.run_once:
                await run_once(settings=settings)
                return

            await worker_loop(interval_minutes, settings=settings)
        finally:
            await close_delivery_clients()
            await dispose_engine()

    asyncio.run(runner())


if __name__ == "__main__":
    main()
