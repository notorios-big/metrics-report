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


# ---------------------------------------------------------------------------
# Ad-level insights (for the "ads" sheet)
# ---------------------------------------------------------------------------


def fetch_ad_insights_by_day(
    *,
    api_version: str,
    ad_account_id: str,
    access_token: str,
    since_ymd: str,
    until_ymd: str,
) -> list[dict[str, Any]]:
    """Fetch daily insights broken down by individual ad."""
    url = f"https://graph.facebook.com/{api_version}/{ad_account_id}/insights"
    params: dict[str, str] = {
        "fields": ",".join([
            "ad_name", "adset_name", "campaign_name",
            "spend", "impressions", "clicks", "inline_link_clicks",
            "actions", "video_thruplay_watched_actions",
            "video_avg_time_watched_actions",
        ]),
        "level": "ad",
        "time_range": json.dumps({"since": since_ymd, "until": until_ymd}),
        "time_increment": "1",
        "limit": "5000",
        "access_token": access_token,
    }

    out: list[dict[str, Any]] = []
    while True:
        resp = request_json("GET", url, params=params)
        if "error" in resp:
            raise RuntimeError(f"Meta Ads API error: {resp['error']}")
        out.extend(resp.get("data") or [])
        next_url = (
            (resp.get("paging") or {}).get("next")
            if isinstance(resp.get("paging"), dict)
            else None
        )
        if not next_url:
            break
        url = next_url
        params = {}

    _LOG.info("Meta Ads (ad-level) returned %d rows", len(out))
    return out


def _extract_action(actions: list[dict[str, Any]] | None, *type_names: str) -> int:
    """Return the integer value for the first matching action_type."""
    if not actions:
        return 0
    for a in actions:
        if a.get("action_type") in type_names:
            try:
                return int(float(a.get("value", 0)))
            except (TypeError, ValueError):
                pass
    return 0


def ad_insights_to_sheet_rows(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert ad-level insight rows into sheet-ready dicts."""

    def _int(v: Any) -> int:
        try:
            return int(float(v))
        except (TypeError, ValueError):
            return 0

    def _float(v: Any) -> float:
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    rows: list[dict[str, Any]] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        date = it.get("date_start")
        if not isinstance(date, str) or not date:
            continue

        spend = _float(it.get("spend"))
        if spend == 0.0:
            continue

        actions = it.get("actions") if isinstance(it.get("actions"), list) else []
        impressions = _int(it.get("impressions"))

        # 3-second video views → Hook Rate numerator
        video_views_3s = _extract_action(actions, "video_view")

        # ThruPlay → Hold Rate numerator
        thruplay_raw = it.get("video_thruplay_watched_actions")
        thruplay = 0
        if isinstance(thruplay_raw, list) and thruplay_raw:
            try:
                thruplay = int(float(thruplay_raw[0].get("value", 0)))
            except (TypeError, ValueError, IndexError):
                pass

        # Average video watch time (seconds)
        avg_time_raw = it.get("video_avg_time_watched_actions")
        avg_time = 0.0
        if isinstance(avg_time_raw, list) and avg_time_raw:
            try:
                avg_time = round(float(avg_time_raw[0].get("value", 0)), 2)
            except (TypeError, ValueError, IndexError):
                pass

        hook_rate = round(video_views_3s / impressions, 4) if impressions > 0 else 0.0
        hold_rate = round(thruplay / video_views_3s, 4) if video_views_3s > 0 else 0.0

        rows.append({
            "Ad": it.get("ad_name", ""),
            "Adset": it.get("adset_name", ""),
            "Campaña": it.get("campaign_name", ""),
            "Fecha": date,
            "Inversión": spend,
            "ATC": _extract_action(actions, "add_to_cart", "omni_add_to_cart"),
            "IC": _extract_action(actions, "initiate_checkout", "omni_initiated_checkout"),
            "Purchase": _extract_action(actions, "purchase", "omni_purchase"),
            "Impresiones": impressions,
            "Clicks": _int(it.get("clicks")),
            "Visitas": _int(it.get("inline_link_clicks")),
            "Tiempo promedio": avg_time,
            "Hook Rate": hook_rate,
            "Hold Rate": hold_rate,
        })

    rows.sort(key=lambda r: (r["Fecha"], r["Campaña"], r["Adset"], r["Ad"]))
    return rows
