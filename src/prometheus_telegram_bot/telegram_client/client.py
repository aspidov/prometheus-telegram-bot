from __future__ import annotations

import asyncio
from html import escape
from io import BytesIO
import logging
from typing import Awaitable, Callable

from telegram import BotCommand, Message, Update
from telegram.ext import Application, ApplicationBuilder, CommandHandler, ContextTypes

from prometheus_telegram_bot.config import TelegramConfig
from prometheus_telegram_bot.visualizer import VisualizationResult


logger = logging.getLogger(__name__)


TelegramCommandHandler = Callable[
    [Update, ContextTypes.DEFAULT_TYPE],
    Awaitable[None],
]


class TelegramClient:
    def __init__(self, config: TelegramConfig) -> None:
        self._config = config
        if not config.bot_token:
            raise ValueError(
                "Telegram bot token is required. Set TELEGRAM_BOT_TOKEN in .env or provide telegram.bot_token in config."
            )
        self._application: Application = ApplicationBuilder().token(
            config.bot_token
        ).build()
        self._commands: list[BotCommand] = []
        self._stop_event = asyncio.Event()

    def add_command_handler(
        self,
        command_name: str,
        handler: TelegramCommandHandler,
        description: str,
    ) -> None:
        self._application.add_handler(CommandHandler(command_name, handler))
        self._commands.append(BotCommand(command_name, description))
        logger.info("Registered Telegram command /%s", command_name)

    async def start(self) -> None:
        logger.info("Initializing Telegram application")
        await self._application.initialize()
        if self._commands:
            await self._application.bot.set_my_commands(self._commands)
            logger.info("Published %s Telegram command(s)", len(self._commands))
        await self._application.start()
        if self._application.updater is None:
            raise RuntimeError("Telegram updater is not available")
        await self._application.updater.start_polling()
        logger.info("Telegram polling started")

    async def wait_until_stopped(self) -> None:
        await self._stop_event.wait()

    async def stop(self) -> None:
        self._stop_event.set()
        if self._application.updater is not None:
            await self._application.updater.stop()
        await self._application.stop()
        await self._application.shutdown()
        logger.info("Telegram application stopped")

    async def send_text(self, text: str, *, chat_id: int | str) -> Message:
        logger.info("Sending Telegram text message to chat_id=%s", chat_id)
        rendered_text = self._render_text(text)
        return await self._application.bot.send_message(
            chat_id=chat_id,
            text=rendered_text,
            parse_mode=self._config.parse_mode,
            disable_notification=self._config.disable_notification,
            message_thread_id=self._config.message_thread_id,
        )

    async def send_visualization(
        self,
        visualization: VisualizationResult,
        *,
        chat_id: int | str,
    ) -> Message:
        if visualization.image_bytes is None:
            logger.info("Sending Telegram text visualization to chat_id=%s", chat_id)
            rendered_text = self._render_text(visualization.caption, allow_markup=visualization.preformatted)
            return await self._application.bot.send_message(
                chat_id=chat_id,
                text=rendered_text,
                parse_mode=self._config.parse_mode,
                disable_notification=self._config.disable_notification,
                message_thread_id=self._config.message_thread_id,
            )

        image = BytesIO(visualization.image_bytes)
        image.name = visualization.filename
        image.seek(0)
        logger.info("Sending Telegram image visualization to chat_id=%s filename=%s", chat_id, visualization.filename)

        rendered_caption = self._render_text(
            visualization.caption,
            allow_markup=visualization.preformatted,
        )
        return await self._application.bot.send_photo(
            chat_id=chat_id,
            photo=image,
            caption=rendered_caption,
            parse_mode=self._config.parse_mode,
            disable_notification=self._config.disable_notification,
            message_thread_id=self._config.message_thread_id,
        )

    def _render_text(self, text: str, *, allow_markup: bool = False) -> str:
        if self._config.parse_mode == "HTML" and not allow_markup:
            return escape(text)
        return text
