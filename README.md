# Prometheus Telegram Bot

[![Docker Hub](https://img.shields.io/badge/Docker%20Hub-andreybolut%2Fprometheus--telegram--bot-2496ED?logo=docker&logoColor=white)](https://hub.docker.com/r/andreybolut/prometheus-telegram-bot)

Telegram bot for scheduled and on-demand Prometheus statistics.

It supports:
- predefined metric commands in Telegram
- scheduled publishing with cron expressions
- custom PromQL queries from Telegram
- multiple PromQL queries on one chart
- value, graph, and pie chart rendering
- persistent access control with admin approval
- local development and Docker deployment

## Features

- Query Prometheus with predefined PromQL expressions
- Render results as:
	- `value`
	- `graph`
	- `piechart`
- Trigger metrics manually with Telegram commands like `/current`
- Send metrics automatically on cron schedules
- Stack multiple named metrics on one graph or chart
- Allow optional custom PromQL execution through a Telegram command like `/query up`
- Persist permissions and pending access requests on disk
- Automatically assign the first `/start` user as administrator

## How it works

The application is split into simple modules:

- config loading and validation
- Telegram communication
- Prometheus querying
- visualization
- scheduling
- access control

At startup the bot:
1. loads YAML config
2. initializes Prometheus, Telegram, scheduler, and access-control services
3. starts Telegram polling
4. listens for user commands
5. sends scheduled metrics to all allowed chats

## Access control

Access is chat-based and persisted in a JSON state file.

Rules:
- the first user who sends `/start` becomes admin automatically
- users not yet allowed will create a pending request on `/start`
- admins can approve or deny requests
- only allowed chats can use metrics and custom queries
- scheduled messages are sent only to allowed chats

Admin commands:
- `/pending`
- `/approve <chat_id>`
- `/deny <chat_id>`

## Requirements

- Python 3.12+
- a Telegram bot token from BotFather
- a reachable Prometheus server

## Quick start (local)

### 1. Install dependencies

Using `uv`:

```bash
uv sync --group dev
```

### 2. Configure the bot

Copy and edit the example config in [examples/bot-config.yaml](examples/bot-config.yaml).

Full field-by-field documentation is available in [docs/configuration-reference.md](docs/configuration-reference.md).

At minimum set:
- `prometheus.base_url`
- `access_control.state_file`

Telegram token resolution order:
1. `TELEGRAM_BOT_TOKEN` from the process environment
2. `TELEGRAM_BOT_TOKEN` loaded from a `.env` file if the environment variable is not already set
3. `telegram.bot_token` from YAML config

The loader checks `.env` in:
- the config file directory
- the current working directory

You can start from [.env.example](.env.example).

### 3. Run locally

Using the packaged CLI:

```bash
uv run prometheus-telegram-bot --config examples/bot-config.yaml
```

Using the local example runner:

```bash
uv run python examples/main.py
```

Or with an explicit config path:

```bash
uv run python examples/main.py --config examples/bot-config.yaml
```

## Docker

The image is generic and does not bundle example config files.

Container contract:
- entrypoint: `prometheus-telegram-bot`
- pass config with `--config /path/to/config.yaml`
- mount a writable folder for persisted access-control state
- optionally provide `TELEGRAM_BOT_TOKEN` via environment or mounted `.env`
- built-in container health check reuses the running container config path automatically

### Example with Docker Compose

See [examples/docker-compose.yml](examples/docker-compose.yml).

Run:

```bash
docker compose -f examples/docker-compose.yml up -d --build
```

The sample compose file mounts:
- config at `/config/bot-config.yaml`
- data directory at `/data`

### Example with `docker run`

```bash
docker run -d \
	--name prometheus-telegram-bot \
	-v $(pwd)/config.yaml:/config/config.yaml:ro \
	-v $(pwd)/data:/data \
	andreybolut/prometheus-telegram-bot:latest \
	--config /config/config.yaml
```

## Configuration

See the full configuration reference in [docs/configuration-reference.md](docs/configuration-reference.md).

Quick pointers:

- use [examples/bot-config.yaml](examples/bot-config.yaml) as the starting template
- for Docker persistence, set `access_control.state_file` under `/data`
- for token resolution and field details, see [docs/configuration-reference.md](docs/configuration-reference.md)

## Telegram usage

Typical flow:

1. first user sends `/start`
2. that user becomes admin automatically
3. later users send `/start`
4. admin receives approval request
5. admin runs `/approve <chat_id>`
6. approved user can run metric commands

Example user commands:
- `/start`
- `/help`
- `/current`
- `/random_graph`
- `/system_graph`
- `/health`
- `/query up`

## Development

### Run tests

```bash
uv run pytest
```

### Install lint hooks

```bash
uv run pre-commit install
```

Run lint manually with:

```bash
uv run ruff check .
```

Current tests cover:
- config loading
- dotenv token loading and YAML fallback
- command-only metric config support
- access-control bootstrap and approval flow
- multi-query metric config and merge behavior

### Project layout

- [src/prometheus_telegram_bot/config/models.py](src/prometheus_telegram_bot/config/models.py) — config schema
- [src/prometheus_telegram_bot/access_control/service.py](src/prometheus_telegram_bot/access_control/service.py) — permission persistence and approvals
- [src/prometheus_telegram_bot/telegram_client/client.py](src/prometheus_telegram_bot/telegram_client/client.py) — Telegram API integration
- [src/prometheus_telegram_bot/prometheus/client.py](src/prometheus_telegram_bot/prometheus/client.py) — Prometheus queries
- [src/prometheus_telegram_bot/visualizer/service.py](src/prometheus_telegram_bot/visualizer/service.py) — chart/value rendering
- [src/prometheus_telegram_bot/scheduler/service.py](src/prometheus_telegram_bot/scheduler/service.py) — cron scheduling
- [src/prometheus_telegram_bot/application.py](src/prometheus_telegram_bot/application.py) — application wiring
- [src/prometheus_telegram_bot/entrypoint/main.py](src/prometheus_telegram_bot/entrypoint/main.py) — CLI entrypoint

## Notes

- `graph` publishers use Prometheus range queries
- `value` and `piechart` publishers use instant queries
- the bot currently uses chat-based authorization
- for production, prefer a persistent mounted data directory for `access_control.state_file`

## License

Released under the [MIT License](LICENSE).
