from __future__ import annotations

from dataclasses import dataclass
import logging

from prometheus_telegram_bot.config import (
    CustomPromqlCommandConfig,
    MetricQuery,
    MetricPublisher,
    MetricPublisherType,
    VisualizerConfig,
)
from prometheus_telegram_bot.prometheus import (
    PrometheusClient,
    PrometheusQueryResult,
    PrometheusSample,
    PrometheusSeries,
)
from prometheus_telegram_bot.telegram_client import TelegramClient
from prometheus_telegram_bot.visualizer import VisualizationResult, Visualizer


QUERY_NAME_LABEL = "query"
logger = logging.getLogger(__name__)


@dataclass(slots=True)
class PublisherService:
    prometheus: PrometheusClient
    visualizer: Visualizer
    visualizer_config: VisualizerConfig
    telegram: TelegramClient

    async def fetch_rendered(self, publisher: MetricPublisher) -> VisualizationResult:
        logger.info("Fetching and rendering publisher=%s type=%s", publisher.metric_name, publisher.type)
        result = await self._query_for_publisher(publisher)
        return self.visualizer.render(publisher, result)

    async def publish_to_chat(self, publisher: MetricPublisher, chat_id: int | str) -> None:
        logger.info("Publishing publisher=%s to chat_id=%s", publisher.metric_name, chat_id)
        visualization = await self.fetch_rendered(publisher)
        await self.telegram.send_visualization(visualization, chat_id=chat_id)

    async def broadcast(self, publisher: MetricPublisher, chat_ids: list[int | str]) -> None:
        logger.info("Broadcasting publisher=%s to %s chat(s)", publisher.metric_name, len(chat_ids))
        visualization = await self.fetch_rendered(publisher)
        for chat_id in chat_ids:
            await self.telegram.send_visualization(visualization, chat_id=chat_id)

    async def run_custom_query(
        self,
        promql_query: str,
        custom_config: CustomPromqlCommandConfig,
    ) -> VisualizationResult:
        logger.info("Running custom query with render type=%s", custom_config.default_type)
        publisher = MetricPublisher(
            name="Custom query",
            metric_name="custom_query",
            cron_expression=None,
            type=custom_config.default_type,
            promql_query=promql_query,
            time_period=custom_config.time_period,
            available_via_command=True,
            command_name=custom_config.command_name,
        )
        result = await self._query_for_publisher(publisher)
        return self.visualizer.render(publisher, result)

    async def _query_for_publisher(
        self,
        publisher: MetricPublisher,
    ) -> PrometheusQueryResult:
        metric_queries = _resolve_metric_queries(publisher)
        logger.info("Resolving %s Prometheus quer%s for publisher=%s", len(metric_queries), "y" if len(metric_queries) == 1 else "ies", publisher.metric_name)
        results: list[PrometheusQueryResult] = []
        for metric_query in metric_queries:
            if publisher.type == MetricPublisherType.GRAPH:
                logger.info(
                    "Executing range query for publisher=%s query_name=%s lookback=%s step=%s",
                    publisher.metric_name,
                    metric_query.name,
                    publisher.time_period or self.visualizer_config.default_time_period,
                    self.visualizer_config.default_step,
                )
                result = await self.prometheus.range_query(
                    metric_query.promql_query,
                    lookback=publisher.time_period or self.visualizer_config.default_time_period,
                    step=self.visualizer_config.default_step,
                )
            else:
                logger.info(
                    "Executing instant query for publisher=%s query_name=%s",
                    publisher.metric_name,
                    metric_query.name,
                )
                result = await self.prometheus.instant_query(metric_query.promql_query)
            results.append(result)

        return _merge_query_results(publisher, metric_queries, results)


def _resolve_metric_queries(publisher: MetricPublisher) -> list[MetricQuery]:
    if publisher.promql_queries:
        return publisher.promql_queries
    if publisher.promql_query is None:
        raise ValueError("Metric publisher must define promql_query or promql_queries")
    return [MetricQuery(name=publisher.name, promql_query=publisher.promql_query)]


def _merge_query_results(
    publisher: MetricPublisher,
    metric_queries: list[MetricQuery],
    results: list[PrometheusQueryResult],
) -> PrometheusQueryResult:
    merged_series: list[PrometheusSeries] = []
    include_query_label = len(metric_queries) > 1
    for metric_query, result in zip(metric_queries, results, strict=True):
        for series in result.series:
            series_labels = (
                {QUERY_NAME_LABEL: metric_query.name, **series.labels}
                if include_query_label
                else dict(series.labels)
            )
            merged_series.append(
                PrometheusSeries(
                    labels=series_labels,
                    samples=[
                        PrometheusSample(
                            labels=(
                                {QUERY_NAME_LABEL: metric_query.name, **sample.labels}
                                if include_query_label
                                else dict(sample.labels)
                            ),
                            timestamp=sample.timestamp,
                            value=sample.value,
                        )
                        for sample in series.samples
                    ],
                )
            )

    merged_result_type = "matrix" if publisher.type == MetricPublisherType.GRAPH else "vector"
    return PrometheusQueryResult(result_type=merged_result_type, series=merged_series)
