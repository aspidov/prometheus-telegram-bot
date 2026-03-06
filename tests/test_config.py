from __future__ import annotations

from pathlib import Path

import pytest

from prometheus_telegram_bot.config import load_bot_config


def test_example_config_loads() -> None:
    config = load_bot_config(Path("examples/bot-config.yaml"))

    assert config.scheduler.enabled is True
    assert config.telegram.custom_promql.enabled is True
    assert len(config.metric_publishers) >= 1


def test_command_only_metric_is_supported(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
access_control:
  state_file: tmp/access-control.json
telegram:
  bot_token: test-token
  parse_mode: HTML
prometheus:
  base_url: http://localhost:9090
metric_publishers:
  - name: On demand metric
    metric_name: on_demand_metric
    available_via_command: true
    command_name: demand
    type: value
    promql_query: up
""".strip(),
        encoding="utf-8",
    )

    config = load_bot_config(config_path)
    publisher = config.metric_publishers[0]

    assert publisher.cron_expression is None
    assert publisher.available_via_command is True
    assert publisher.command_name == "demand"


def test_telegram_bot_token_loaded_from_dotenv(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.chdir(tmp_path)

    config_path = tmp_path / "config.yaml"
    dotenv_path = tmp_path / ".env"

    dotenv_path.write_text("TELEGRAM_BOT_TOKEN=dotenv-token\n", encoding="utf-8")
    config_path.write_text(
        """
access_control:
  state_file: tmp/access-control.json
telegram:
  bot_token: yaml-token
prometheus:
  base_url: http://localhost:9090
metric_publishers: []
""".strip(),
        encoding="utf-8",
    )

    config = load_bot_config(config_path)

    assert config.telegram.bot_token == "dotenv-token"


def test_telegram_bot_token_falls_back_to_yaml_config(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.chdir(tmp_path)

    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
access_control:
  state_file: tmp/access-control.json
telegram:
  bot_token: yaml-token
prometheus:
  base_url: http://localhost:9090
metric_publishers: []
""".strip(),
        encoding="utf-8",
    )

    config = load_bot_config(config_path)

    assert config.telegram.bot_token == "yaml-token"


def test_duplicate_metric_names_are_rejected(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.chdir(tmp_path)

    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
access_control:
  state_file: tmp/access-control.json
telegram:
  bot_token: yaml-token
prometheus:
  base_url: http://localhost:9090
metric_publishers:
  - name: Metric one
    metric_name: duplicate_metric
    available_via_command: true
    command_name: one
    type: value
    promql_query: up
  - name: Metric two
    metric_name: duplicate_metric
    available_via_command: true
    command_name: two
    type: value
    promql_query: up
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="metric_name values must be unique"):
        load_bot_config(config_path)


def test_duplicate_command_names_are_rejected(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.chdir(tmp_path)

    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
access_control:
  state_file: tmp/access-control.json
telegram:
  bot_token: yaml-token
prometheus:
  base_url: http://localhost:9090
metric_publishers:
  - name: Metric one
    metric_name: metric_one
    available_via_command: true
    command_name: duplicate
    type: value
    promql_query: up
  - name: Metric two
    metric_name: metric_two
    available_via_command: true
    command_name: duplicate
    type: value
    promql_query: up
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Telegram command names must be unique"):
        load_bot_config(config_path)


def test_reserved_command_names_are_rejected(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.chdir(tmp_path)

    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
access_control:
  state_file: tmp/access-control.json
telegram:
  bot_token: yaml-token
prometheus:
  base_url: http://localhost:9090
metric_publishers:
  - name: Health metric
    metric_name: health_metric
    available_via_command: true
    command_name: start
    type: value
    promql_query: up
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Telegram command names must be unique"):
        load_bot_config(config_path)


def test_metric_requires_schedule_or_command_access(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.chdir(tmp_path)

    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
access_control:
  state_file: tmp/access-control.json
telegram:
  bot_token: yaml-token
prometheus:
  base_url: http://localhost:9090
metric_publishers:
  - name: Invalid metric
    metric_name: invalid_metric
    type: value
    promql_query: up
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match="Metric publisher must define cron_expression or set available_via_command to true",
    ):
        load_bot_config(config_path)


def test_command_name_requires_command_access(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.chdir(tmp_path)

    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
access_control:
  state_file: tmp/access-control.json
telegram:
  bot_token: yaml-token
prometheus:
  base_url: http://localhost:9090
metric_publishers:
  - name: Invalid metric
    metric_name: invalid_metric
    cron_expression: "*/5 * * * *"
    command_name: invalid
    type: value
    promql_query: up
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match="command_name can be set only when available_via_command is true|command_name must be omitted when available_via_command is false",
    ):
        load_bot_config(config_path)


def test_multi_query_metric_config_is_supported(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.chdir(tmp_path)

    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
access_control:
  state_file: tmp/access-control.json
telegram:
  bot_token: yaml-token
prometheus:
  base_url: http://localhost:9090
metric_publishers:
  - name: System metrics
    metric_name: system_metrics
    cron_expression: "*/5 * * * *"
    type: graph
    promql_queries:
      - name: CPU
        promql_query: cpu_usage
      - name: Memory
        promql_query: memory_usage
""".strip(),
        encoding="utf-8",
    )

    config = load_bot_config(config_path)

    assert config.metric_publishers[0].promql_query is None
    assert len(config.metric_publishers[0].promql_queries) == 2


def test_single_and_multi_query_fields_cannot_be_combined(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.chdir(tmp_path)

    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
access_control:
  state_file: tmp/access-control.json
telegram:
  bot_token: yaml-token
prometheus:
  base_url: http://localhost:9090
metric_publishers:
  - name: Invalid metric
    metric_name: invalid_metric
    cron_expression: "*/5 * * * *"
    type: graph
    promql_query: cpu_usage
    promql_queries:
      - name: Memory
        promql_query: memory_usage
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Use either promql_query or promql_queries, not both"):
        load_bot_config(config_path)
