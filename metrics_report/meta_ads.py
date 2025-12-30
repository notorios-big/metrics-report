from __future__ import annotations

import json
import logging
from collections import defaultdict
from typing import Any

from metrics_report.http import request_json


_LOG = logging.getLogger(__name__)


def fetch_account_insights_by_day(
    *,
    api_version: str,
    ad_account_id: str,
    access_token: str,
    since_ymd: str,
    until_ymd: str,
) -> list[dict[str, Any]]:
    url = f"https://graph.facebook.com/{api_version}/{ad_account_id}/insights"
    params = {
        "fields": "spend,impressions,reach,inline_link_clicks",
        "level": "account",
        "time_range": json.dumps({"since": since_ymd, "until": until_ymd}),
        "time_increment": "1",
        "limit": "5000",
        "access_token": access_token,
    }

    out: list[dict[str, Any]] = []
    while True:
        resp = request_json("GET", url, params={k: str(v) for k, v in params.items()})
        if "error" in resp:
            raise RuntimeError(f"Meta API error: {resp['error']}")
        out.extend(resp.get("data") or [])
        next_url = ((resp.get("paging") or {}).get("next")) if isinstance(resp.get("paging"), dict) else None
        if not next_url:
            break
        url = next_url
        params = {}

    _LOG.info("Meta returned %d rows", len(out))
    return out


def insights_to_sheet_rows(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_date: dict[str, dict[str, float]] = defaultdict(
        lambda: {"spend": 0.0, "impressions": 0.0, "reach": 0.0, "clicks": 0.0}
    )
    for it in items:
        if not isinstance(it, dict):
            continue
        date = it.get("date_start")
        if not isinstance(date, str) or not date:
            continue

        def to_int(v: Any) -> int:
            try:
                return int(float(v))
            except (TypeError, ValueError):
                return 0

        def to_float(v: Any) -> float:
            try:
                return float(v)
            except (TypeError, ValueError):
                return 0.0

        acc = by_date[date]
        acc["spend"] += to_float(it.get("spend"))
        acc["impressions"] += float(to_int(it.get("impressions")))
        acc["reach"] += float(to_int(it.get("reach")))
        acc["clicks"] += float(to_int(it.get("inline_link_clicks")))

    rows: list[dict[str, Any]] = []
    for date in sorted(by_date.keys()):
        acc = by_date[date]
        rows.append(
            {
                "Fecha": date,
                "Inversión - CLP": acc["spend"],
                "Impresiones": int(acc["impressions"]),
                "Alcance": int(acc["reach"]),
                "Visitas": int(acc["clicks"]),
            }
        )
    return rows
