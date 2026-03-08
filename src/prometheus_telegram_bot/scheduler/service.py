from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from croniter import croniter

from prometheus_telegram_bot.access_control import AccessControlService
from prometheus_telegram_bot.config import MetricPublisher, SchedulerConfig
from prometheus_telegram_bot.publisher_service import PublisherService


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _ScheduledPublisher:
    publisher: MetricPublisher
    iterator: croniter
    next_run: datetime


class SchedulerService:
    def __init__(
        self,
        config: SchedulerConfig,
        publishers: list[MetricPublisher],
        publisher_service: PublisherService,
        access_control: AccessControlService,
    ) -> None:
        self._config = config
        self._publisher_service = publisher_service
        self._access_control = access_control
        now = datetime.now(tz=UTC)
        self._jobs: list[_ScheduledPublisher] = []
        for publisher in publishers:
            if publisher.cron_expression is None:
                continue

            iterator = croniter(publisher.cron_expression, now)
            self._jobs.append(
                _ScheduledPublisher(
                    publisher=publisher,
                    iterator=iterator,
                    next_run=iterator.get_next(datetime),
                )
            )
        logger.info("Scheduler initialized with %s scheduled job(s)", len(self._jobs))

    async def run(self, stop_event: asyncio.Event) -> None:
        if not self._config.enabled or not self._jobs:
            logger.info(
                "Scheduler idle: enabled=%s scheduled_jobs=%s",
                self._config.enabled,
                len(self._jobs),
            )
            await stop_event.wait()
            return

        logger.info("Scheduler loop started")
        while not stop_event.is_set():
            now = datetime.now(tz=UTC)
            jobs_to_run: list[_ScheduledPublisher] = []
            
            for job in self._jobs:
                if job.next_run <= now:
                    jobs_to_run.append(job)
                    job.next_run = job.iterator.get_next(datetime)
                    
            if jobs_to_run:
                allowed_chat_ids = self._access_control.allowed_chat_ids()
                if allowed_chat_ids:
                    logger.info(
                        "Running %s scheduled publishers for %s allowed chat(s)",
                        len(jobs_to_run),
                        len(allowed_chat_ids),
                    )
                    publishers = [job.publisher for job in jobs_to_run]
                    try:
                        await self._publisher_service.broadcast_multiple(
                            publishers,
                            allowed_chat_ids,
                        )
                    except Exception as exc:
                        publisher_names = ", ".join(p.metric_name for p in publishers)
                        logger.exception("Scheduled publish failed for publishers=%s", publisher_names)
                        for admin_chat_id in self._access_control.allowed_chat_ids():
                            if self._access_control.is_admin(admin_chat_id):
                                await self._publisher_service.telegram.send_text(
                                    f"Failed to publish {publisher_names}: {exc}",
                                    chat_id=admin_chat_id,
                                )
                                
            for job in jobs_to_run:
                logger.info(
                    "Next run for publisher=%s scheduled at %s",
                    job.publisher.metric_name,
                    job.next_run.isoformat(),
                )

            next_due = min(job.next_run for job in self._jobs)
            timeout_seconds = min(
                self._config.poll_interval_seconds,
                max(0.0, (next_due - datetime.now(tz=UTC)).total_seconds()),
            )
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=timeout_seconds)
            except TimeoutError:
                pass
        logger.info("Scheduler loop stopped")
