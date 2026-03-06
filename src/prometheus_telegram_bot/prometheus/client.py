from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import logging
from typing import Any

import httpx

from prometheus_telegram_bot.config import PrometheusConfig


logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class PrometheusSample:
    labels: dict[str, str]
    timestamp: datetime
    value: float


@dataclass(slots=True, frozen=True)
class PrometheusSeries:
    labels: dict[str, str]
    samples: list[PrometheusSample]

    @property
    def latest_value(self) -> float:
        return self.samples[-1].value


@dataclass(slots=True, frozen=True)
class PrometheusQueryResult:
    result_type: str
    series: list[PrometheusSeries]


class PrometheusClient:
    def __init__(self, config: PrometheusConfig) -> None:
        self._config = config
        self._client = httpx.AsyncClient(
            base_url=str(config.base_url).rstrip("/"),
            timeout=config.request_timeout_seconds,
            verify=config.verify_ssl,
        )
        logger.info(
            "Initialized Prometheus client for %s with timeout=%ss verify_ssl=%s",
            config.base_url,
            config.request_timeout_seconds,
            config.verify_ssl,
        )

    async def healthcheck(self) -> None:
        logger.info("Checking Prometheus health endpoint")
        response = await self._client.get("/-/healthy")
        response.raise_for_status()
        logger.info("Prometheus healthcheck succeeded")

    async def close(self) -> None:
        await self._client.aclose()
        logger.info("Closed Prometheus client")

    async def instant_query(self, query: str, query_time: datetime | None = None) -> PrometheusQueryResult:
        logger.info("Executing Prometheus instant query")
        params: dict[str, Any] = {"query": query}
        if query_time is not None:
            params["time"] = query_time.astimezone(UTC).isoformat()

        payload = await self._request_json("/api/v1/query", params)
        return self._parse_query_result(payload)

    async def range_query(
        self,
        query: str,
        *,
        lookback: str,
        step: str,
        end_time: datetime | None = None,
    ) -> PrometheusQueryResult:
        logger.info("Executing Prometheus range query lookback=%s step=%s", lookback, step)
        resolved_end_time = end_time or datetime.now(tz=UTC)
        start_time = resolved_end_time - _parse_prometheus_duration(lookback)

        payload = await self._request_json(
            "/api/v1/query_range",
            {
                "query": query,
                "start": start_time.isoformat(),
                "end": resolved_end_time.isoformat(),
                "step": step,
            },
        )
        return self._parse_query_result(payload)

    async def _request_json(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        logger.debug("Sending Prometheus request path=%s params=%s", path, params)
        response = await self._client.get(path, params=params)
        response.raise_for_status()
        payload = response.json()
        if payload.get("status") != "success":
            raise ValueError(f"Prometheus query failed: {payload}")
        logger.info("Prometheus request path=%s succeeded", path)
        return payload

    def _parse_query_result(self, payload: dict[str, Any]) -> PrometheusQueryResult:
        data = payload["data"]
        result_type = data["resultType"]
        raw_result = data["result"]
        series: list[PrometheusSeries] = []

        if result_type == "scalar":
            timestamp, value = raw_result
            series.append(
                PrometheusSeries(
                    labels={},
                    samples=[_build_sample({}, timestamp, value)],
                )
            )
        else:
            value_key = "value" if result_type == "vector" else "values"
            for item in raw_result:
                labels = {str(key): str(val) for key, val in item.get("metric", {}).items()}
                raw_samples = item.get(value_key, [])
                if result_type == "vector":
                    raw_samples = [raw_samples]
                samples = [_build_sample(labels, timestamp, value) for timestamp, value in raw_samples]
                series.append(PrometheusSeries(labels=labels, samples=samples))

        logger.info("Parsed Prometheus result type=%s series=%s", result_type, len(series))
        return PrometheusQueryResult(result_type=result_type, series=series)


def _build_sample(labels: dict[str, str], timestamp: float | str, value: str) -> PrometheusSample:
    return PrometheusSample(
        labels=labels,
        timestamp=datetime.fromtimestamp(float(timestamp), tz=UTC),
        value=float(value),
    )


def _parse_prometheus_duration(duration: str) -> timedelta:
    unit = duration[-1]
    value = int(duration[:-1])
    if unit == "s":
        return timedelta(seconds=value)
    if unit == "m":
        return timedelta(minutes=value)
    if unit == "h":
        return timedelta(hours=value)
    if unit == "d":
        return timedelta(days=value)
    if unit == "w":
        return timedelta(weeks=value)
    raise ValueError(f"Unsupported duration unit in {duration}")
