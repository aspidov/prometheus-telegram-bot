from __future__ import annotations

import logging
import os
from pathlib import Path

import yaml
from pydantic import ValidationError
from dotenv import load_dotenv

from .models import BotConfig


logger = logging.getLogger(__name__)


def load_bot_config(config_path: Path) -> BotConfig:
    _load_local_dotenv_files(config_path)
    logger.info("Loading bot config from %s", config_path)

    with config_path.open("r", encoding="utf-8") as config_file:
        raw_config = yaml.safe_load(config_file) or {}

    if not isinstance(raw_config, dict):
        raise ValueError("Config file root must be a YAML mapping/object")

    telegram_config = raw_config.setdefault("telegram", {})
    if not isinstance(telegram_config, dict):
        raise ValueError("telegram config must be a YAML mapping/object")

    env_bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    if env_bot_token:
        telegram_config["bot_token"] = env_bot_token
        logger.info("Using TELEGRAM_BOT_TOKEN from environment")

    try:
        config = BotConfig.model_validate(raw_config)
        logger.info(
            "Loaded config with %s metric publisher(s), scheduler enabled=%s",
            len(config.metric_publishers),
            config.scheduler.enabled,
        )
        return config
    except ValidationError as exc:
        logger.exception("Failed to validate config file %s", config_path)
        raise ValueError(f"Invalid config file: {exc}") from exc


def _load_local_dotenv_files(config_path: Path) -> None:
    candidates = [config_path.parent / ".env", Path.cwd() / ".env"]
    seen_paths: set[Path] = set()

    for candidate in candidates:
        resolved_candidate = candidate.resolve()
        if resolved_candidate in seen_paths or not candidate.is_file():
            continue

        load_dotenv(dotenv_path=candidate, override=False)
        logger.info("Loaded .env values from %s", candidate)
        seen_paths.add(resolved_candidate)
