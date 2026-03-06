from __future__ import annotations

import re
from pathlib import Path
from enum import StrEnum

from pydantic import (
	AnyHttpUrl,
	BaseModel,
	ConfigDict,
	Field,
	ValidationInfo,
	field_validator,
	model_validator,
)


CRON_EXPRESSION_PATTERN = re.compile(
	r"^\s*(\S+\s+){4,6}\S+\s*$"
)
LOOKBACK_PERIOD_PATTERN = re.compile(r"^\d+[smhdw]$")
COMMAND_NAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,31}$")
BUILTIN_COMMAND_NAMES = {
	"start",
	"help",
	"approve",
	"deny",
	"pending",
}


class MetricPublisherType(StrEnum):
	VALUE = "value"
	GRAPH = "graph"
	PIECHART = "piechart"


class TelegramParseMode(StrEnum):
	HTML = "HTML"
	MARKDOWN = "Markdown"
	MARKDOWN_V2 = "MarkdownV2"


class CustomPromqlCommandConfig(BaseModel):
	model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

	enabled: bool = False
	command_name: str = "query"
	default_type: MetricPublisherType = MetricPublisherType.VALUE
	time_period: str | None = None

	@field_validator("command_name")
	@classmethod
	def validate_command_name(cls, value: str) -> str:
		if not COMMAND_NAME_PATTERN.match(value):
			raise ValueError(
				"command_name must start with a letter and contain only letters, numbers, and underscores"
			)
		return value.lower()

	@field_validator("time_period")
	@classmethod
	def validate_time_period(cls, value: str | None) -> str | None:
		if value is None:
			return value
		if not LOOKBACK_PERIOD_PATTERN.match(value):
			raise ValueError(
				"time_period must be a lookback duration like '15m' or '2h'"
			)
		return value


class SchedulerConfig(BaseModel):
	model_config = ConfigDict(extra="forbid")

	enabled: bool = True
	poll_interval_seconds: int = Field(default=15, gt=0)


class AccessControlConfig(BaseModel):
	model_config = ConfigDict(extra="forbid")

	state_file: Path = Path("/data/access-control.json")
	admin_chat_ids: list[int | str] = Field(default_factory=list)
	allowed_chat_ids: list[int | str] = Field(default_factory=list)


class TelegramConfig(BaseModel):
	model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

	bot_token: str | None = None
	message_thread_id: int | None = None
	parse_mode: TelegramParseMode | None = TelegramParseMode.HTML
	disable_notification: bool = False
	custom_promql: CustomPromqlCommandConfig = Field(
		default_factory=CustomPromqlCommandConfig
	)

	@field_validator("bot_token")
	@classmethod
	def validate_bot_token(cls, value: str | None) -> str | None:
		if value is None:
			return value
		if not value.strip():
			return None
		return value


class PrometheusConfig(BaseModel):
	model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

	base_url: AnyHttpUrl
	request_timeout_seconds: float = Field(default=10.0, gt=0)
	verify_ssl: bool = True


class VisualizerConfig(BaseModel):
	model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

	default_time_period: str = "1h"
	default_step: str = "60s"
	figure_width: float = Field(default=10.0, gt=0)
	figure_height: float = Field(default=6.0, gt=0)
	dpi: int = Field(default=150, gt=0)
	style: str = "default"

	@field_validator("default_time_period", "default_step")
	@classmethod
	def validate_duration(cls, value: str) -> str:
		if not LOOKBACK_PERIOD_PATTERN.match(value):
			raise ValueError(
				"Duration values must look like '15m', '2h', or '60s'"
			)
		return value


class MetricQuery(BaseModel):
	model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

	name: str = Field(..., min_length=1)
	promql_query: str = Field(..., min_length=1)


class MetricPublisher(BaseModel):
	model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

	name: str = Field(..., min_length=1)
	metric_name: str = Field(..., min_length=1)
	cron_expression: str | None = None
	type: MetricPublisherType
	promql_query: str | None = None
	promql_queries: list[MetricQuery] = Field(default_factory=list)
	time_period: str | None = None
	available_via_command: bool = False
	command_name: str | None = None

	@field_validator("promql_query")
	@classmethod
	def validate_promql_query(cls, value: str | None) -> str | None:
		if value is None:
			return value
		if not value.strip():
			return None
		return value

	@field_validator("cron_expression")
	@classmethod
	def validate_cron_expression(cls, value: str | None) -> str | None:
		if value is None:
			return value
		if not CRON_EXPRESSION_PATTERN.match(value):
			raise ValueError(
				"cron_expression must be a valid cron string with 5 to 7 fields"
			)
		return value

	@field_validator("time_period")
	@classmethod
	def validate_time_period(cls, value: str | None) -> str | None:
		if value is None:
			return value

		if not LOOKBACK_PERIOD_PATTERN.match(value):
			raise ValueError(
				"time_period must be a lookback duration like '15m' or '2h'"
			)
		return value

	@field_validator("command_name")
	@classmethod
	def validate_command_name(
		cls,
		value: str | None,
		info: ValidationInfo,
	) -> str | None:
		if value is None:
			return value

		if not info.data.get("available_via_command", False):
			raise ValueError(
				"command_name can be set only when available_via_command is true"
			)

		if not COMMAND_NAME_PATTERN.match(value):
			raise ValueError(
				"command_name must start with a letter and contain only letters, numbers, and underscores"
			)
		return value.lower()

	@model_validator(mode="after")
	def validate_triggering(self) -> MetricPublisher:
		if self.cron_expression is None and not self.available_via_command:
			raise ValueError(
				"Metric publisher must define cron_expression or set available_via_command to true"
			)

		if self.available_via_command and not self.command_name:
			raise ValueError(
				"command_name is required when available_via_command is true"
			)

		if not self.available_via_command and self.command_name is not None:
			raise ValueError(
				"command_name must be omitted when available_via_command is false"
			)

		if self.promql_query is None and not self.promql_queries:
			raise ValueError(
				"Metric publisher must define promql_query or promql_queries"
			)

		if self.promql_query is not None and self.promql_queries:
			raise ValueError(
				"Use either promql_query or promql_queries, not both"
			)

		return self


class BotConfig(BaseModel):
	model_config = ConfigDict(extra="forbid")

	access_control: AccessControlConfig = Field(default_factory=AccessControlConfig)
	telegram: TelegramConfig
	prometheus: PrometheusConfig
	scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)
	visualizer: VisualizerConfig = Field(default_factory=VisualizerConfig)
	metric_publishers: list[MetricPublisher] = Field(default_factory=list)

	@model_validator(mode="after")
	def validate_unique_names(self) -> BotConfig:
		metric_names = [publisher.metric_name for publisher in self.metric_publishers]
		if len(metric_names) != len(set(metric_names)):
			raise ValueError("metric_name values must be unique")

		command_names = list(BUILTIN_COMMAND_NAMES)
		command_names.extend(
			publisher.command_name
			for publisher in self.metric_publishers
			if publisher.command_name is not None
		)
		if self.telegram.custom_promql.enabled:
			command_names.append(self.telegram.custom_promql.command_name)

		if len(command_names) != len(set(command_names)):
			raise ValueError("Telegram command names must be unique")

		return self
