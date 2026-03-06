from __future__ import annotations

import pytest

from prometheus_telegram_bot.config import TelegramConfig
from prometheus_telegram_bot.telegram_client import TelegramClient


def test_telegram_client_requires_token() -> None:
    with pytest.raises(ValueError, match="Telegram bot token is required"):
        TelegramClient(TelegramConfig(bot_token=None))


def test_render_text_escapes_html_when_parse_mode_is_html() -> None:
    client = TelegramClient(TelegramConfig(bot_token="token", parse_mode="HTML"))

    rendered = client._render_text("Use <promql> and <chat_id>")

    assert rendered == "Use &lt;promql&gt; and &lt;chat_id&gt;"


def test_render_text_preserves_plain_text_when_parse_mode_is_disabled() -> None:
    client = TelegramClient(TelegramConfig(bot_token="token", parse_mode=None))

    rendered = client._render_text("Use <promql> and <chat_id>")

    assert rendered == "Use <promql> and <chat_id>"


def test_render_text_preserves_allowed_html_markup() -> None:
    client = TelegramClient(TelegramConfig(bot_token="token", parse_mode="HTML"))

    rendered = client._render_text("Value: <b>42.5</b>", allow_markup=True)

    assert rendered == "Value: <b>42.5</b>"
