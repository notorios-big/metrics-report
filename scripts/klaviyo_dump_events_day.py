#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from datetime import date, timedelta
from typing import Any

import requests

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:
    load_dotenv = None


def _require(name: str) -> str:
    value = (os.getenv(name) or "").strip()
    if not value:
        raise SystemExit(f"Missing env var: {name}")
    return value


def _iter_pages(url: str, *, headers: dict[str, str], params: dict[str, str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    while True:
        resp = requests.get(url, headers=headers, params=params, timeout=60)
        resp.raise_for_status()
        payload = resp.json()
        data = payload.get("data") or []
        if isinstance(data, list):
            out.extend([x for x in data if isinstance(x, dict)])

        links = payload.get("links") if isinstance(payload, dict) else None
        next_url = links.get("next") if isinstance(links, dict) else None
        if not isinstance(next_url, str) or not next_url:
            break

        url = next_url
        params = {}
    return out


def main(argv: list[str]) -> int:
    if load_dotenv is not None:
        load_dotenv(".env", override=False)

    day = argv[1] if len(argv) > 1 else ""
    if not day or len(day) != 10:
        raise SystemExit("Usage: scripts/klaviyo_dump_events_day.py YYYY-MM-DD")

    try:
        day_obj = date.fromisoformat(day)
    except ValueError as e:
        raise SystemExit(f"Invalid day: {day!r}") from e
    end_day = (day_obj + timedelta(days=1)).isoformat()

    metric_id = _require("KLAVIYO_METRIC_ID")
    private_key = _require("KLAVIYO_PRIVATE_KEY")
    revision = (os.getenv("KLAVIYO_REVISION") or "2025-07-15").strip()

    url = "https://a.klaviyo.com/api/events/"
    headers = {
        "Authorization": f"Klaviyo-API-Key {private_key}",
        "revision": revision,
        "Accept": "application/json",
    }
    params = {
        "page[size]": "100",
        "filter": "and("
        + f"equals(metric_id,\"{metric_id}\"),"
        + f"greater-or-equal(datetime,{day}T00:00:00),"
        + f"less-than(datetime,{end_day}T00:00:00)"
        + ")",
    }

    events = _iter_pages(url, headers=headers, params=params)

    for ev in events:
        sys.stdout.write(json.dumps(ev, ensure_ascii=False) + "\n")

    sys.stderr.write(f"events={len(events)} day={day} metric_id={metric_id}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
