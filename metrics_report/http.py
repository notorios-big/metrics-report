from __future__ import annotations

import json
import time
from typing import Any

import requests


class HttpError(RuntimeError):
    pass


def request_json(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    params: dict[str, str] | None = None,
    json_body: dict[str, Any] | None = None,
    timeout_s: int = 60,
    max_retries: int = 3,
) -> dict[str, Any]:
    retry_statuses = {429, 500, 502, 503, 504}
    last_error: Exception | None = None
    for attempt in range(max_retries):
        resp = requests.request(
            method=method,
            url=url,
            headers=headers,
            params=params,
            json=json_body,
            timeout=timeout_s,
        )
        if resp.status_code in retry_statuses and attempt < max_retries - 1:
            time.sleep(2**attempt)
            continue
        try:
            resp.raise_for_status()
        except requests.HTTPError as e:
            msg = f"{method} {url} failed: {resp.status_code} {resp.text[:2000]}"
            raise HttpError(msg) from e
        try:
            return resp.json()
        except json.JSONDecodeError as e:
            last_error = e
            break
    raise HttpError(f"{method} {url} did not return JSON") from last_error

