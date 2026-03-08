from __future__ import annotations

import asyncio
from html import escape
from io import BytesIO
import logging
from typing import Awaitable, Callable

from telegram import BotCommand, Message, Update, InputMediaPhoto
from telegram.ext import Application, ApplicationBuilder, CommandHandler, ContextTypes

from prometheus_telegram_bot.config import TelegramConfig
from prometheus_telegram_bot.visualizer import VisualizationResult


logger = logging.getLogger(__name__)

_PHOTO_CAPTION_LIMIT = 1024
_TEXT_MESSAGE_LIMIT = 4096
_MEDIA_GROUP_MAX = 10


def _split_text(text: str, limit: int) -> list[str]:
    """Split *text* into chunks of at most *limit* characters.

    Splits on double-newline paragraph boundaries when possible so that
    individual publisher captions stay intact.
    """
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    current = ""
    for paragraph in text.split("\n\n"):
        candidate = f"{current}\n\n{paragraph}" if current else paragraph
        if len(candidate) <= limit:
            current = candidate
        else:
            if current:
                chunks.append(current)
            # If a single paragraph exceeds the limit, hard-split it.
            while len(paragraph) > limit:
                chunks.append(paragraph[:limit])
                paragraph = paragraph[limit:]
            current = paragraph
    if current:
        chunks.append(current)
    return chunks


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

    async def send_visualizations(
        self,
        visualizations: list[VisualizationResult],
        *,
        chat_id: int | str,
    ) -> list[Message]:
        if not visualizations:
            return []

        image_vizs = [v for v in visualizations if v.image_bytes is not None]
        text_vizs = [v for v in visualizations if v.image_bytes is None]

        messages: list[Message] = []

        # --- Handle image visualizations ---
        if image_vizs:
            if len(image_vizs) == 1:
                viz = image_vizs[0]
                image = BytesIO(viz.image_bytes)
                image.name = viz.filename
                image.seek(0)
                caption = self._render_text(viz.caption, allow_markup=viz.preformatted)

                if len(caption) > _PHOTO_CAPTION_LIMIT:
                    logger.info(
                        "Caption too long (%s chars) for single photo, sending photo + text to chat_id=%s",
                        len(caption), chat_id,
                    )
                    msg = await self._application.bot.send_photo(
                        chat_id=chat_id,
                        photo=image,
                        disable_notification=self._config.disable_notification,
                        message_thread_id=self._config.message_thread_id,
                    )
                    messages.append(msg)
                    for chunk in _split_text(caption, _TEXT_MESSAGE_LIMIT):
                        msg = await self._application.bot.send_message(
                            chat_id=chat_id,
                            text=chunk,
                            parse_mode=self._config.parse_mode,
                            disable_notification=self._config.disable_notification,
                            message_thread_id=self._config.message_thread_id,
                        )
                        messages.append(msg)
                else:
                    logger.info("Sending multi-visualization with 1 image to chat_id=%s", chat_id)
                    msg = await self._application.bot.send_photo(
                        chat_id=chat_id,
                        photo=image,
                        caption=caption,
                        parse_mode=self._config.parse_mode,
                        disable_notification=self._config.disable_notification,
                        message_thread_id=self._config.message_thread_id,
                    )
                    messages.append(msg)
            else:
                # Multiple images → send_media_group (max 10 per group).
                # Each photo gets its OWN caption; overflow captions sent as text.
                for batch_start in range(0, len(image_vizs), _MEDIA_GROUP_MAX):
                    batch = image_vizs[batch_start : batch_start + _MEDIA_GROUP_MAX]
                    media_group: list[InputMediaPhoto] = []
                    overflow_captions: list[str] = []

                    for viz in batch:
                        image = BytesIO(viz.image_bytes)
                        image.name = viz.filename
                        image.seek(0)
                        caption = self._render_text(viz.caption, allow_markup=viz.preformatted)

                        if len(caption) > _PHOTO_CAPTION_LIMIT:
                            overflow_captions.append(caption)
                            media_group.append(InputMediaPhoto(media=image))
                        else:
                            media_group.append(
                                InputMediaPhoto(
                                    media=image,
                                    caption=caption,
                                    parse_mode=self._config.parse_mode,
                                )
                            )

                    logger.info(
                        "Sending media group of %s images to chat_id=%s", len(media_group), chat_id,
                    )
                    msgs = await self._application.bot.send_media_group(
                        chat_id=chat_id,
                        media=media_group,
                        disable_notification=self._config.disable_notification,
                        message_thread_id=self._config.message_thread_id,
                    )
                    messages.extend(msgs)

                    if overflow_captions:
                        combined = "\n\n".join(overflow_captions)
                        for chunk in _split_text(combined, _TEXT_MESSAGE_LIMIT):
                            msg = await self._application.bot.send_message(
                                chat_id=chat_id,
                                text=chunk,
                                parse_mode=self._config.parse_mode,
                                disable_notification=self._config.disable_notification,
                                message_thread_id=self._config.message_thread_id,
                            )
                            messages.append(msg)

        # --- Handle text-only visualizations ---
        if text_vizs:
            combined_text = "\n\n".join(
                self._render_text(v.caption, allow_markup=v.preformatted) for v in text_vizs
            )
            for chunk in _split_text(combined_text, _TEXT_MESSAGE_LIMIT):
                logger.info("Sending text visualization to chat_id=%s", chat_id)
                msg = await self._application.bot.send_message(
                    chat_id=chat_id,
                    text=chunk,
                    parse_mode=self._config.parse_mode,
                    disable_notification=self._config.disable_notification,
                    message_thread_id=self._config.message_thread_id,
                )
                messages.append(msg)

        return messages

    def _render_text(self, text: str, *, allow_markup: bool = False) -> str:
        if self._config.parse_mode == "HTML" and not allow_markup:
            return escape(text)
        return text
