from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

from metrics_report.http import request_json


_LOG = logging.getLogger(__name__)


def build_metric_aggregates_body(
    *,
    metric_id: str,
    start_ymd: str,
    end_exclusive_ymd: str,
    timezone: str,
    by: tuple[str, ...] = (),
) -> dict[str, Any]:
    return {
        "data": {
            "type": "metric-aggregate",
            "attributes": {
                "measurements": ["count"],
                "by": list(by),
                "filter": [
                    f"greater-or-equal(datetime,{start_ymd}T00:00:00)",
                    f"less-than(datetime,{end_exclusive_ymd}T00:00:00)",
                ],
                "metric_id": metric_id,
                "interval": "day",
                "timezone": timezone,
            },
        }
    }


def fetch_metric_aggregates(
    *,
    private_key: str,
    revision: str,
    body: dict[str, Any],
) -> dict[str, Any]:
    url = "https://a.klaviyo.com/api/metric-aggregates"
    headers = {
        "Authorization": f"Klaviyo-API-Key {private_key}",
        "revision": revision,
        "Content-Type": "application/json",
    }
    return request_json("POST", url, headers=headers, json_body=body)


def metric_aggregates_to_sheet_rows(resp: dict[str, Any]) -> list[dict[str, Any]]:
    attributes = (((resp.get("data") or {}).get("attributes")) or {}) if isinstance(resp.get("data"), dict) else {}
    dates = attributes.get("dates") or []
    data = attributes.get("data") or []
    if not isinstance(dates, list):
        _LOG.info("Klaviyo response missing dates")
        return []

    totals_by_date: dict[str, int] = defaultdict(int)

    for d in dates:
        if isinstance(d, str) and len(d) >= 10:
            totals_by_date[d[:10]] += 0

    if not isinstance(data, list):
        _LOG.info("Klaviyo response missing data")
        data = []

    for series in data:
        counts: list[Any] | None = None
        if isinstance(series, dict):
            measurements = series.get("measurements") if isinstance(series.get("measurements"), dict) else {}
            candidate = measurements.get("count") or []
            if isinstance(candidate, list):
                counts = candidate
        elif isinstance(series, list):
            counts = series

        if counts is None:
            continue

        for i, d in enumerate(dates):
            if not isinstance(d, str) or len(d) < 10:
                continue
            date = d[:10]
            count = counts[i] if i < len(counts) else 0
            try:
                count_int = int(count)
            except (TypeError, ValueError):
                count_int = 0
            totals_by_date[date] += count_int

    rows: list[dict[str, Any]] = []
    for date in sorted(totals_by_date.keys()):
        rows.append({"Fecha": date, "Suscriptores": totals_by_date[date]})
    return rows
