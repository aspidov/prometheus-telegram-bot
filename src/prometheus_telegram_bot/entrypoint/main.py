from __future__ import annotations

import asyncio
import argparse
import logging
from pathlib import Path
from typing import Sequence

from prometheus_telegram_bot import build_application
from prometheus_telegram_bot.config import load_bot_config
from prometheus_telegram_bot.prometheus import PrometheusClient


logger = logging.getLogger(__name__)


def _existing_file_path(path_value: str) -> Path:
	path = Path(path_value)
	if not path.exists():
		raise argparse.ArgumentTypeError(f"Config file does not exist: {path}")
	if not path.is_file():
		raise argparse.ArgumentTypeError(f"Config path is not a file: {path}")
	return path


def build_parser() -> argparse.ArgumentParser:
	parser = argparse.ArgumentParser(
		prog="prometheus-telegram-bot",
		description="Run Prometheus Telegram bot with YAML config",
	)
	parser.add_argument(
		"-c",
		"--config",
		type=_existing_file_path,
		help="Path to YAML config file",
		metavar="FILE",
	)
	parser.add_argument(
		"--healthcheck",
		action="store_true",
		help="Validate container health by loading config, checking the bot token, and probing Prometheus",
	)
	return parser


def _resolve_healthcheck_config_path(cmdline_path: Path = Path("/proc/1/cmdline")) -> Path:
	if cmdline_path.is_file():
		args = [item for item in cmdline_path.read_bytes().decode("utf-8").split("\x00") if item]
		for index, arg in enumerate(args[:-1]):
			if arg in {"-c", "--config"}:
				logger.info("Resolved healthcheck config path from process command line: %s", args[index + 1])
				return _existing_file_path(args[index + 1])

	default_path = Path("/config/bot-config.yaml")
	logger.info("Using default healthcheck config path: %s", default_path)
	return _existing_file_path(str(default_path))


def _configure_logging() -> None:
	logging.basicConfig(
		level=logging.INFO,
		format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
	)


async def _run_from_config(config_path: Path) -> int:
	config = load_bot_config(config_path)
	application = build_application(config)
	try:
		logger.info(
			"Starting application with %s metric publisher(s), Prometheus endpoint %s, access-control state %s",
			len(config.metric_publishers),
			config.prometheus.base_url,
			config.access_control.state_file,
		)
		await application.run()
		return 0
	finally:
		logger.info("Application exited")


async def _run_healthcheck(config_path: Path) -> int:
	logger.info("Running healthcheck with config %s", config_path)
	config = load_bot_config(config_path)
	if not config.telegram.bot_token:
		raise ValueError(
			"Telegram bot token is required. Set TELEGRAM_BOT_TOKEN in .env or provide telegram.bot_token in config."
		)

	prometheus = PrometheusClient(config.prometheus)
	try:
		await prometheus.healthcheck()
		logger.info("Healthcheck passed for Prometheus endpoint %s", config.prometheus.base_url)
		return 0
	finally:
		await prometheus.close()


def main(argv: Sequence[str] | None = None) -> int:
	_configure_logging()
	parser = build_parser()
	args = parser.parse_args(argv)

	try:
		if args.healthcheck:
			config_path = args.config or _resolve_healthcheck_config_path()
			return asyncio.run(_run_healthcheck(config_path))
		if args.config is None:
			parser.error("the following arguments are required: -c/--config")
		return asyncio.run(_run_from_config(args.config))
	except ValueError as exc:
		parser.error(str(exc))
	return 2


if __name__ == "__main__":
	raise SystemExit(main())
