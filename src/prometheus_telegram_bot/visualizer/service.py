from __future__ import annotations

from dataclasses import dataclass
from html import escape
from io import BytesIO

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from prometheus_telegram_bot.config import MetricPublisher, MetricPublisherType, VisualizerConfig
from prometheus_telegram_bot.prometheus import PrometheusQueryResult, PrometheusSeries


@dataclass(slots=True, frozen=True)
class VisualizationResult:
    caption: str
    image_bytes: bytes | None = None
    filename: str = "chart.png"
    preformatted: bool = False


class Visualizer:
    def __init__(self, config: VisualizerConfig) -> None:
        self._config = config

    def render(self, publisher: MetricPublisher, result: PrometheusQueryResult) -> VisualizationResult:
        if publisher.type == MetricPublisherType.VALUE:
            return self._render_value(publisher, result)
        if publisher.type == MetricPublisherType.GRAPH:
            return self._render_graph(publisher, result)
        if publisher.type == MetricPublisherType.PIECHART:
            return self._render_piechart(publisher, result)
        raise ValueError(f"Unsupported publisher type: {publisher.type}")

    def _render_value(self, publisher: MetricPublisher, result: PrometheusQueryResult) -> VisualizationResult:
        if not result.series:
            return VisualizationResult(
                caption=f"{escape(_publisher_title(publisher))}\nNo data returned from Prometheus.",
                preformatted=True,
            )

        lines = [escape(_publisher_title(publisher))]
        for index, series in enumerate(result.series, start=1):
            label = escape(_series_label(series, index))
            lines.append(f"• {label}: <b>{series.latest_value:g}</b>")
        if publisher.promql_queries:
            query_names = escape(", ".join(query.name for query in publisher.promql_queries))
            lines.append(f"• Queries: {query_names}")
        return VisualizationResult(caption="\n".join(lines), preformatted=True)

    def _render_graph(self, publisher: MetricPublisher, result: PrometheusQueryResult) -> VisualizationResult:
        if not result.series:
            return VisualizationResult(caption=f"{_publisher_title(publisher)}\nNo data returned from Prometheus.")

        with plt.style.context(self._config.style):
            figure, axis = plt.subplots(
                figsize=(self._config.figure_width, self._config.figure_height),
                dpi=self._config.dpi,
            )
            for index, series in enumerate(result.series, start=1):
                x_values = [sample.timestamp for sample in series.samples]
                y_values = [sample.value for sample in series.samples]
                axis.plot(x_values, y_values, label=_series_label(series, index))

            axis.set_title(publisher.name)
            axis.set_xlabel("Time")
            axis.set_ylabel("Value")
            axis.grid(True, alpha=0.3)
            if len(result.series) > 1 or any(series.labels for series in result.series):
                axis.legend()
            figure.autofmt_xdate()

            buffer = BytesIO()
            figure.tight_layout()
            figure.savefig(buffer, format="png")
            plt.close(figure)

        return VisualizationResult(
            caption=_build_caption(publisher),
            image_bytes=buffer.getvalue(),
            filename=f"{publisher.name.replace(' ', '_').lower()}_graph.png",
        )

    def _render_piechart(self, publisher: MetricPublisher, result: PrometheusQueryResult) -> VisualizationResult:
        if not result.series:
            return VisualizationResult(caption=f"{_publisher_title(publisher)}\nNo data returned from Prometheus.")

        labels = []
        sizes = []
        for index, series in enumerate(result.series, start=1):
            labels.append(_series_label(series, index))
            sizes.append(series.latest_value)

        with plt.style.context(self._config.style):
            figure, axis = plt.subplots(
                figsize=(self._config.figure_width, self._config.figure_height),
                dpi=self._config.dpi,
            )
            axis.pie(sizes, labels=labels, autopct="%1.1f%%", startangle=90)
            axis.set_title(publisher.name)
            axis.axis("equal")
            if len(result.series) > 1 or any(series.labels for series in result.series):
                axis.legend(loc="upper left")

            buffer = BytesIO()
            figure.tight_layout()
            figure.savefig(buffer, format="png")
            plt.close(figure)

        return VisualizationResult(
            caption=_build_caption(publisher),
            image_bytes=buffer.getvalue(),
            filename=f"{publisher.name.replace(' ', '_').lower()}_piechart.png",
        )


def _series_label(series: PrometheusSeries, index: int) -> str:
    if not series.labels:
        return f"Series {index}"
    return ", ".join(f"{key}={value}" for key, value in sorted(series.labels.items()))


def _build_caption(publisher: MetricPublisher) -> str:
    lines = [_publisher_title(publisher)]
    if publisher.promql_queries:
        query_names = ", ".join(query.name for query in publisher.promql_queries)
        lines.append(f"• Queries: {query_names}")
    else:
        lines.append(f"• Query: {publisher.promql_query}")

    if publisher.time_period:
        lines.append(f"• Lookback: {publisher.time_period}")

    return "\n".join(lines)


def _publisher_title(publisher: MetricPublisher) -> str:
    icons = {
        MetricPublisherType.VALUE: "📊",
        MetricPublisherType.GRAPH: "📈",
        MetricPublisherType.PIECHART: "🥧",
    }
    return f"{icons[publisher.type]} {publisher.name}"
