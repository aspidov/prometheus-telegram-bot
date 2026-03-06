# Configuration Reference

This document describes the full YAML configuration format for Prometheus Telegram Bot.

For a working example, see [examples/bot-config.yaml](../examples/bot-config.yaml).

## Root structure

The config file root supports these sections:

- `access_control`
- `telegram`
- `prometheus`
- `scheduler`
- `visualizer`
- `metric_publishers`

## Example

```yaml
access_control:
  state_file: "/data/access-control.json"
  admin_chat_ids: []
  allowed_chat_ids: []

telegram:
  bot_token: null
  parse_mode: "HTML"
  disable_notification: false
  custom_promql:
    enabled: true
    command_name: "query"
    default_type: "value"

prometheus:
  base_url: "http://localhost:9090"
  request_timeout_seconds: 10
  verify_ssl: true

scheduler:
  enabled: true
  poll_interval_seconds: 15

visualizer:
  default_time_period: "1h"
  default_step: "60s"
  figure_width: 10
  figure_height: 6
  dpi: 150
  style: "default"

metric_publishers:
  - name: "Current random metric"
    metric_name: "current_random_metric"
    cron_expression: "*/5 * * * *"
    available_via_command: true
    command_name: "current"
    type: "value"
    promql_query: "example_random_metric"
```

## `access_control`

- `state_file`: path to the JSON file used to persist admins, allowed chats, and pending requests
- `admin_chat_ids`: optional seeded admin chat IDs
- `allowed_chat_ids`: optional seeded allowed chat IDs

Notes:

- admin chat IDs are automatically added to the allowed set
- the first user who sends `/start` becomes admin if no admins exist yet
- for Docker deployments, keep `state_file` under `/data` so state survives container recreation

## `telegram`

- `bot_token`: optional YAML fallback for the Telegram bot token
- `message_thread_id`: optional Telegram topic/thread ID
- `parse_mode`: `HTML`, `Markdown`, `MarkdownV2`, or `null`
- `disable_notification`: disable Telegram notifications for bot messages
- `custom_promql`: settings for the custom query command

Token resolution order:

1. `TELEGRAM_BOT_TOKEN` from the process environment
2. `TELEGRAM_BOT_TOKEN` loaded from a local `.env` file
3. `telegram.bot_token` from YAML config

The loader checks `.env` in:

- the config file directory
- the current working directory

### `telegram.custom_promql`

- `enabled`: enable or disable custom query execution
- `command_name`: Telegram command name, for example `query`
- `default_type`: render type for custom queries: `value`, `graph`, or `piechart`
- `time_period`: optional default lookback duration such as `15m` or `2h`

## `prometheus`

- `base_url`: base URL of the Prometheus server
- `request_timeout_seconds`: HTTP request timeout in seconds
- `verify_ssl`: whether to verify TLS certificates

## `scheduler`

- `enabled`: enable scheduled publishing
- `poll_interval_seconds`: scheduler wake-up interval in seconds

## `visualizer`

- `default_time_period`: fallback lookback duration for graph publishers
- `default_step`: Prometheus range query step
- `figure_width`: matplotlib figure width
- `figure_height`: matplotlib figure height
- `dpi`: output image DPI
- `style`: matplotlib style name

## `metric_publishers`

Each item in `metric_publishers` defines one report that can be scheduled, triggered by command, or both.

Fields:

- `name`: human-readable title shown in Telegram
- `metric_name`: unique internal identifier
- `cron_expression`: optional cron expression for scheduled publishing
- `type`: `value`, `graph`, or `piechart`
- `promql_query`: single PromQL expression
- `promql_queries`: optional list of named PromQL expressions for multi-series charts
- `time_period`: optional lookback duration such as `15m`, `1h`, or `1d`
- `available_via_command`: whether the metric can be triggered manually in Telegram
- `command_name`: Telegram command name when `available_via_command` is enabled

Rules:

- define either `promql_query` or `promql_queries`, not both
- `metric_name` values must be unique
- Telegram command names must be unique
- `cron_expression` is optional only when `available_via_command` is `true`
- `command_name` is required when `available_via_command` is `true`

### Multi-query publishers

Use `promql_queries` when one chart should combine multiple named PromQL expressions.

Example:

```yaml
metric_publishers:
  - name: "System Load"
    metric_name: "system_load"
    available_via_command: true
    command_name: "system_load"
    type: "graph"
    time_period: "1h"
    promql_queries:
      - name: "API"
        promql_query: "rate(http_requests_total[5m])"
      - name: "Worker"
        promql_query: "rate(worker_jobs_total[5m])"
```

## Duration formats

The project accepts short Prometheus-style duration strings such as:

- `60s`
- `15m`
- `2h`
- `1d`
- `1w`

## Command examples

Depending on your config, typical Telegram commands include:

- `/start`
- `/help`
- `/current`
- `/random_graph`
- `/health`
- `/query up`