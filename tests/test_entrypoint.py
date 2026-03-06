from __future__ import annotations

import importlib
from pathlib import Path

entrypoint_module = importlib.import_module("prometheus_telegram_bot.entrypoint.main")


def test_healthcheck_resolves_config_from_cmdline(tmp_path: Path) -> None:
  config_path = tmp_path / "config.yaml"
  config_path.write_text("telegram:\n  bot_token: test-token\nprometheus:\n  base_url: http://localhost:9090\n", encoding="utf-8")
  cmdline_path = tmp_path / "cmdline"
  cmdline_path.write_bytes(
    b"prometheus-telegram-bot\x00--config\x00" + str(config_path).encode("utf-8") + b"\x00"
  )

  resolved = entrypoint_module._resolve_healthcheck_config_path(cmdline_path)

  assert resolved == config_path


def test_main_runs_healthcheck_mode(monkeypatch, tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
telegram:
  bot_token: test-token
prometheus:
  base_url: http://localhost:9090
metric_publishers:
  - name: On-demand health status
    metric_name: health_status
    available_via_command: true
    command_name: health
    type: value
    promql_query: up
""".strip(),
        encoding="utf-8",
    )

    called: dict[str, Path] = {}

    async def fake_run_healthcheck(path: Path) -> int:
        called["config_path"] = path
        return 0

    monkeypatch.setattr(entrypoint_module, "_run_healthcheck", fake_run_healthcheck)

    exit_code = entrypoint_module.main(["--config", str(config_path), "--healthcheck"])

    assert exit_code == 0
    assert called["config_path"] == config_path