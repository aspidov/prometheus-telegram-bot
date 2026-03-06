from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from dataclasses import dataclass, field

from telegram import Chat, Update, User
from telegram.ext import ContextTypes

from prometheus_telegram_bot.access_control import AccessControlService, AccessRequest
from prometheus_telegram_bot.config import BotConfig
from prometheus_telegram_bot.prometheus import PrometheusClient
from prometheus_telegram_bot.publisher_service import PublisherService
from prometheus_telegram_bot.scheduler import SchedulerService
from prometheus_telegram_bot.telegram_client import TelegramClient
from prometheus_telegram_bot.visualizer import Visualizer


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ApplicationContext:
    config: BotConfig
    access_control: AccessControlService
    telegram: TelegramClient
    prometheus: PrometheusClient
    visualizer: Visualizer
    publisher_service: PublisherService
    scheduler: SchedulerService
    _stop_event: asyncio.Event = field(default_factory=asyncio.Event)
    _scheduler_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        logger.info("Registering Telegram handlers")
        self._register_handlers()
        logger.info("Starting Telegram client")
        await self.telegram.start()
        logger.info("Starting scheduler task")
        self._scheduler_task = asyncio.create_task(self.scheduler.run(self._stop_event))

    async def run(self) -> None:
        logger.info("Application run loop started")
        await self.start()
        try:
            await self.telegram.wait_until_stopped()
        finally:
            await self.aclose()

    async def aclose(self) -> None:
        logger.info("Shutting down application")
        self._stop_event.set()
        if self._scheduler_task is not None:
            self._scheduler_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._scheduler_task
        await self.telegram.stop()
        await self.prometheus.close()
        logger.info("Application shutdown complete")

    def _register_handlers(self) -> None:
        self.telegram.add_command_handler(
            "start",
            self._handle_start,
            "Request access or initialize the bot",
        )
        self.telegram.add_command_handler(
            "help",
            self._handle_help,
            "Show available commands",
        )
        self.telegram.add_command_handler(
            "approve",
            self._handle_approve,
            "Approve a pending access request",
        )
        self.telegram.add_command_handler(
            "deny",
            self._handle_deny,
            "Deny a pending access request",
        )
        self.telegram.add_command_handler(
            "pending",
            self._handle_pending,
            "List pending access requests",
        )

        for publisher in self.config.metric_publishers:
            if publisher.available_via_command and publisher.command_name is not None:
                self.telegram.add_command_handler(
                    publisher.command_name,
                    self._build_metric_handler(publisher.metric_name),
                    publisher.name,
                )

        if self.config.telegram.custom_promql.enabled:
            self.telegram.add_command_handler(
                self.config.telegram.custom_promql.command_name,
                self._handle_custom_promql,
                "Run a custom PromQL query",
            )
        logger.info(
            "Registered %s metric command handler(s); custom query enabled=%s",
            sum(
                1
                for publisher in self.config.metric_publishers
                if publisher.available_via_command and publisher.command_name is not None
            ),
            self.config.telegram.custom_promql.enabled,
        )

    def _build_metric_handler(self, metric_name: str):
        async def handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
            await self._handle_metric_command(metric_name, update, context)

        return handler

    async def _handle_help(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        del context
        chat_id = self._chat_id_from_update(update)
        if chat_id is None:
            return
        if not await self._ensure_allowed(update):
            return

        lines = ["Available commands:"]
        for publisher in self.config.metric_publishers:
            if publisher.available_via_command and publisher.command_name is not None:
                lines.append(f"/{publisher.command_name} - {publisher.name}")

        if self.config.telegram.custom_promql.enabled:
            lines.append(
                f"/{self.config.telegram.custom_promql.command_name} <promql> - run a custom query"
            )

        if self.access_control.is_admin(chat_id):
            lines.extend(
                [
                    "/pending - list access requests",
                    "/approve <chat_id> - approve a pending request",
                    "/deny <chat_id> - deny a pending request",
                ]
            )

        await self.telegram.send_text("\n".join(lines), chat_id=chat_id)

    async def _handle_start(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        chat = update.effective_chat
        if chat is None:
            return

        user = update.effective_user
        logger.info("Received /start from chat_id=%s", chat.id)
        decision = self.access_control.register_start_request(
            chat.id,
            display_name=_display_name(chat, user),
            username=user.username if user is not None else None,
        )

        if decision.status == "bootstrap_admin":
            logger.info("Bootstrapped first admin chat_id=%s", chat.id)
            await self.telegram.send_text(
                "You are the first user. Access granted and administrator role assigned.",
                chat_id=chat.id,
            )
            await self._handle_help(update, context)
            return

        if decision.status == "allowed":
            logger.info("Chat already allowed chat_id=%s", chat.id)
            await self.telegram.send_text(
                "Access already granted.",
                chat_id=chat.id,
            )
            await self._handle_help(update, context)
            return

        if decision.status == "pending":
            logger.info("Pending access request already exists for chat_id=%s", chat.id)
            await self.telegram.send_text(
                "Your access request is still pending administrator approval.",
                chat_id=chat.id,
            )
            return

        logger.info("Created new access request for chat_id=%s", chat.id)
        await self.telegram.send_text(
            "Access request submitted. An administrator has been notified.",
            chat_id=chat.id,
        )
        if decision.request is not None:
            await self._notify_admins_about_request(decision.request)

    async def _handle_metric_command(
        self,
        metric_name: str,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        del context
        chat_id = self._chat_id_from_update(update)
        if chat_id is None:
            return
        if not await self._ensure_allowed(update):
            return

        publisher = next(
            (
                item
                for item in self.config.metric_publishers
                if item.metric_name == metric_name
            ),
            None,
        )
        if publisher is None:
            logger.warning("Unknown metric command requested for metric_name=%s chat_id=%s", metric_name, chat_id)
            await self.telegram.send_text("Unknown metric command.", chat_id=chat_id)
            return

        logger.info("Publishing metric %s to chat_id=%s", publisher.metric_name, chat_id)
        await self.publisher_service.publish_to_chat(publisher, chat_id)

    async def _handle_custom_promql(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        chat_id = self._chat_id_from_update(update)
        if chat_id is None:
            return
        if not await self._ensure_allowed(update):
            return

        promql_query = " ".join(context.args).strip()
        if not promql_query:
            command_name = self.config.telegram.custom_promql.command_name
            await self.telegram.send_text(
                f"Usage: /{command_name} <promql>",
                chat_id=chat_id,
            )
            return

        logger.info("Running custom query for chat_id=%s", chat_id)
        visualization = await self.publisher_service.run_custom_query(
            promql_query,
            self.config.telegram.custom_promql,
        )
        await self.telegram.send_visualization(visualization, chat_id=chat_id)

    async def _handle_pending(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        del context
        chat_id = self._chat_id_from_update(update)
        if chat_id is None or not await self._ensure_admin(update):
            return

        pending_requests = self.access_control.pending_requests()
        if not pending_requests:
            await self.telegram.send_text("There are no pending requests.", chat_id=chat_id)
            return

        lines = ["Pending requests:"]
        for request in pending_requests:
            user_line = request.display_name
            if request.username:
                user_line += f" (@{request.username})"
            lines.append(f"- {request.chat_id}: {user_line}")
        await self.telegram.send_text("\n".join(lines), chat_id=chat_id)

    async def _handle_approve(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        await self._handle_access_resolution(update, context, action="approve")

    async def _handle_deny(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        await self._handle_access_resolution(update, context, action="deny")

    async def _handle_access_resolution(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        *,
        action: str,
    ) -> None:
        chat_id = self._chat_id_from_update(update)
        if chat_id is None or not await self._ensure_admin(update):
            return

        if not context.args:
            await self.telegram.send_text(
                f"Usage: /{action} <chat_id>",
                chat_id=chat_id,
            )
            return

        target_chat_id = context.args[0]
        request = (
            self.access_control.approve(target_chat_id)
            if action == "approve"
            else self.access_control.deny(target_chat_id)
        )
        if request is None:
            logger.warning("No pending request found for action=%s target_chat_id=%s", action, target_chat_id)
            await self.telegram.send_text(
                f"No pending request found for chat {target_chat_id}.",
                chat_id=chat_id,
            )
            return

        verb = "approved" if action == "approve" else "denied"
        logger.info("Request %s for chat_id=%s by admin_chat_id=%s", verb, request.chat_id, chat_id)
        await self.telegram.send_text(
            f"Request for chat {request.chat_id} {verb}.",
            chat_id=chat_id,
        )
        await self.telegram.send_text(
            f"Your access request was {verb}.",
            chat_id=request.chat_id,
        )

    async def _notify_admins_about_request(self, request: AccessRequest) -> None:
        admin_chat_ids = [
            chat_id
            for chat_id in self.access_control.allowed_chat_ids()
            if self.access_control.is_admin(chat_id)
        ]
        if not admin_chat_ids:
            logger.info("No admins available to notify about request for chat_id=%s", request.chat_id)
            return

        user_line = request.display_name
        if request.username:
            user_line += f" (@{request.username})"

        text = (
            "New access request received:\n"
            f"Chat ID: {request.chat_id}\n"
            f"User: {user_line}\n"
            f"Approve with /approve {request.chat_id} or deny with /deny {request.chat_id}"
        )
        for admin_chat_id in admin_chat_ids:
            await self.telegram.send_text(text, chat_id=admin_chat_id)
        logger.info("Notified %s admin(s) about access request for chat_id=%s", len(admin_chat_ids), request.chat_id)

    async def _ensure_allowed(self, update: Update) -> bool:
        chat_id = self._chat_id_from_update(update)
        if chat_id is None:
            return False
        if self.access_control.is_allowed(chat_id):
            return True

        logger.info("Rejected command for unauthorized chat_id=%s", chat_id)
        await self.telegram.send_text(
            "Access is not granted. Send /start to request access.",
            chat_id=chat_id,
        )
        return False

    async def _ensure_admin(self, update: Update) -> bool:
        chat_id = self._chat_id_from_update(update)
        if chat_id is None:
            return False
        if self.access_control.is_admin(chat_id):
            return True

        logger.info("Rejected admin command for non-admin chat_id=%s", chat_id)
        await self.telegram.send_text(
            "Administrator access is required for this command.",
            chat_id=chat_id,
        )
        return False

    @staticmethod
    def _chat_id_from_update(update: Update) -> int | None:
        chat = update.effective_chat
        if chat is None:
            return None
        return chat.id


def _display_name(chat: Chat, user: User | None) -> str:
    if user is not None:
        full_name = user.full_name.strip()
        if full_name:
            return full_name
    if chat.title:
        return chat.title
    return str(chat.id)


def build_application(config: BotConfig) -> ApplicationContext:
    access_control = AccessControlService(config.access_control)
    telegram = TelegramClient(config.telegram)
    prometheus = PrometheusClient(config.prometheus)
    visualizer = Visualizer(config.visualizer)
    publisher_service = PublisherService(
        prometheus=prometheus,
        visualizer=visualizer,
        visualizer_config=config.visualizer,
        telegram=telegram,
    )

    return ApplicationContext(
        config=config,
        access_control=access_control,
        telegram=telegram,
        prometheus=prometheus,
        visualizer=visualizer,
        publisher_service=publisher_service,
        scheduler=SchedulerService(
            config=config.scheduler,
            publishers=config.metric_publishers,
            publisher_service=publisher_service,
            access_control=access_control,
        ),
    )
