from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest

from prometheus_telegram_bot.config import MetricPublisher, MetricPublisherType, MetricQuery
from prometheus_telegram_bot.prometheus import PrometheusQueryResult, PrometheusSample, PrometheusSeries
from prometheus_telegram_bot.publisher_service import PublisherService, _merge_query_results, _resolve_metric_queries
from prometheus_telegram_bot.visualizer import VisualizationResult, Visualizer
from prometheus_telegram_bot.config import VisualizerConfig


@dataclass
class FakePrometheusClient:
    instant_results: list[PrometheusQueryResult] = field(default_factory=list)
    range_results: list[PrometheusQueryResult] = field(default_factory=list)
    instant_queries: list[str] = field(default_factory=list)
    range_queries: list[tuple[str, str, str]] = field(default_factory=list)

    async def instant_query(self, query: str) -> PrometheusQueryResult:
        self.instant_queries.append(query)
        return self.instant_results.pop(0)

    async def range_query(self, query: str, *, lookback: str, step: str) -> PrometheusQueryResult:
        self.range_queries.append((query, lookback, step))
        return self.range_results.pop(0)


@dataclass
class FakeTelegramClient:
    sent: list[tuple[int | str, VisualizationResult]] = field(default_factory=list)

    async def send_visualization(self, visualization: VisualizationResult, *, chat_id: int | str) -> None:
        self.sent.append((chat_id, visualization))


def test_resolve_metric_queries_uses_single_query_as_default() -> None:
    publisher = MetricPublisher(
        name="CPU",
        metric_name="cpu",
        cron_expression="*/5 * * * *",
        type=MetricPublisherType.VALUE,
        promql_query="up",
    )

    queries = _resolve_metric_queries(publisher)

    assert len(queries) == 1
    assert queries[0].name == "CPU"
    assert queries[0].promql_query == "up"


def test_merge_query_results_labels_series_with_query_name() -> None:
    publisher = MetricPublisher(
        name="System metrics",
        metric_name="system_metrics",
        cron_expression="*/5 * * * *",
        type=MetricPublisherType.GRAPH,
        promql_queries=[
            MetricQuery(name="CPU", promql_query="cpu_usage"),
            MetricQuery(name="Memory", promql_query="memory_usage"),
        ],
    )
    timestamp = datetime(2026, 3, 6, tzinfo=UTC)
    results = [
        PrometheusQueryResult(
            result_type="matrix",
            series=[
                PrometheusSeries(
                    labels={"instance": "node-1"},
                    samples=[
                        PrometheusSample(labels={"instance": "node-1"}, timestamp=timestamp, value=10.0)
                    ],
                )
            ],
        ),
        PrometheusQueryResult(
            result_type="matrix",
            series=[
                PrometheusSeries(
                    labels={"instance": "node-1"},
                    samples=[
                        PrometheusSample(labels={"instance": "node-1"}, timestamp=timestamp, value=20.0)
                    ],
                )
            ],
        ),
    ]

    merged = _merge_query_results(publisher, publisher.promql_queries, results)

    assert merged.result_type == "matrix"
    assert len(merged.series) == 2
    assert merged.series[0].labels["query"] == "CPU"
    assert merged.series[1].labels["query"] == "Memory"


@pytest.mark.anyio
async def test_publish_to_chat_formats_value_message_from_prometheus_response() -> None:
    timestamp = datetime(2026, 3, 6, tzinfo=UTC)
    publisher = MetricPublisher(
        name="Current CPU",
        metric_name="cpu",
        available_via_command=True,
        command_name="cpu",
        type=MetricPublisherType.VALUE,
        promql_query="sum(rate(cpu_seconds_total[5m]))",
    )
    prometheus = FakePrometheusClient(
        instant_results=[
            PrometheusQueryResult(
                result_type="vector",
                series=[
                    PrometheusSeries(
                        labels={"instance": "node-1", "job": "app"},
                        samples=[
                            PrometheusSample(
                                labels={"instance": "node-1", "job": "app"},
                                timestamp=timestamp,
                                value=42.5,
                            )
                        ],
                    )
                ],
            )
        ]
    )
    telegram = FakeTelegramClient()
    service = PublisherService(
        prometheus=prometheus,
        visualizer=Visualizer(VisualizerConfig()),
        visualizer_config=VisualizerConfig(),
        telegram=telegram,
    )

    await service.publish_to_chat(publisher, chat_id=1234)

    assert prometheus.instant_queries == ["sum(rate(cpu_seconds_total[5m]))"]
    assert telegram.sent == [
        (
            1234,
            VisualizationResult(
                caption="📊 Current CPU\n• instance=node-1, job=app: <b>42.5</b>",
                image_bytes=None,
                filename="chart.png",
                preformatted=True,
            ),
        )
    ]


@pytest.mark.anyio
async def test_broadcast_formats_graph_caption_and_reuses_rendered_image() -> None:
    timestamp = datetime(2026, 3, 6, tzinfo=UTC)
    publisher = MetricPublisher(
        name="System Load",
        metric_name="system_load",
        cron_expression="*/5 * * * *",
        type=MetricPublisherType.GRAPH,
        promql_queries=[
            MetricQuery(name="API", promql_query="rate(http_requests_total[5m])"),
            MetricQuery(name="Worker", promql_query="rate(worker_jobs_total[5m])"),
        ],
        time_period="6h",
    )
    prometheus = FakePrometheusClient(
        range_results=[
            PrometheusQueryResult(
                result_type="matrix",
                series=[
                    PrometheusSeries(
                        labels={"instance": "api-1"},
                        samples=[PrometheusSample(labels={"instance": "api-1"}, timestamp=timestamp, value=10.0)],
                    )
                ],
            ),
            PrometheusQueryResult(
                result_type="matrix",
                series=[
                    PrometheusSeries(
                        labels={"instance": "worker-1"},
                        samples=[PrometheusSample(labels={"instance": "worker-1"}, timestamp=timestamp, value=20.0)],
                    )
                ],
            ),
        ]
    )
    telegram = FakeTelegramClient()
    service = PublisherService(
        prometheus=prometheus,
        visualizer=Visualizer(VisualizerConfig()),
        visualizer_config=VisualizerConfig(default_time_period="1h", default_step="60s"),
        telegram=telegram,
    )

    await service.broadcast(publisher, chat_ids=[1001, 1002])

    assert prometheus.range_queries == [
        ("rate(http_requests_total[5m])", "6h", "60s"),
        ("rate(worker_jobs_total[5m])", "6h", "60s"),
    ]
    assert [chat_id for chat_id, _ in telegram.sent] == [1001, 1002]
    assert telegram.sent[0][1].caption == "📈 System Load\n• Queries: API, Worker\n• Lookback: 6h"
    assert telegram.sent[0][1].filename == "system_load_graph.png"
    assert telegram.sent[0][1].image_bytes is not None
    assert telegram.sent[1][1] == telegram.sent[0][1]


@pytest.mark.anyio
async def test_run_custom_query_uses_default_time_period_in_published_caption() -> None:
    timestamp = datetime(2026, 3, 6, tzinfo=UTC)
    prometheus = FakePrometheusClient(
        range_results=[
            PrometheusQueryResult(
                result_type="matrix",
                series=[
                    PrometheusSeries(
                        labels={},
                        samples=[PrometheusSample(labels={}, timestamp=timestamp, value=99.0)],
                    )
                ],
            )
        ]
    )
    telegram = FakeTelegramClient()
    service = PublisherService(
        prometheus=prometheus,
        visualizer=Visualizer(VisualizerConfig()),
        visualizer_config=VisualizerConfig(default_time_period="30m", default_step="15s"),
        telegram=telegram,
    )

    visualization = await service.run_custom_query(
        "up",
        custom_config=type("CustomConfig", (), {"default_type": MetricPublisherType.GRAPH, "time_period": "30m", "command_name": "query"})(),
    )

    assert prometheus.range_queries == [("up", "30m", "15s")]
    assert visualization.caption == "📈 Custom query\n• Query: up\n• Lookback: 30m"
    assert visualization.filename == "custom_query_graph.png"
    assert visualization.image_bytes is not None
