from __future__ import annotations

import argparse
import asyncio
import logging
import time

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.worker.jobs import run_once


async def worker_loop(interval_minutes: int) -> None:
    logger = logging.getLogger("worker")
    while True:
        start = time.monotonic()
        stats = await run_once()
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

    if args.run_once:
        asyncio.run(run_once())
        return

    asyncio.run(worker_loop(interval_minutes))


if __name__ == "__main__":
    main()

