from __future__ import annotations

import logging
import os
from collections import defaultdict
from pathlib import Path
from typing import Any

import google.auth
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

from metrics_report.http import request_json


_LOG = logging.getLogger(__name__)


def _adc_credentials_path() -> Path | None:
    configured = os.getenv("CLOUDSDK_CONFIG")
    if configured:
        return Path(configured) / "application_default_credentials.json"

    appdata = os.getenv("APPDATA")
    if appdata:
        return Path(appdata) / "gcloud" / "application_default_credentials.json"

    return Path.home() / ".config" / "gcloud" / "application_default_credentials.json"


def get_access_token(*, client_id: str, client_secret: str, refresh_token: str) -> str:
    has_any = bool(client_id or client_secret or refresh_token)
    has_all = bool(client_id and client_secret and refresh_token)

    if has_all:
        creds = Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=client_id,
            client_secret=client_secret,
            scopes=["https://www.googleapis.com/auth/adwords"],
        )
        creds.refresh(Request())
        if not creds.token:
            raise RuntimeError("Failed to refresh Google Ads OAuth token")
        return creds.token

    # If the user started configuring OAuth via env vars but left it incomplete,
    # attempt to fall back to gcloud ADC (common during local development).
    if has_any and not has_all:
        adc = _adc_credentials_path()
        if adc is not None and adc.is_file():
            try:
                creds, _ = google.auth.load_credentials_from_file(
                    adc, scopes=["https://www.googleapis.com/auth/adwords"]
                )
                creds.refresh(Request())
                token = getattr(creds, "token", None)
                if token:
                    _LOG.info(
                        "google_ads: using gcloud ADC token because OAuth env vars are incomplete"
                    )
                    return str(token)
            except Exception:
                # Fall through to a clearer env-var error below.
                pass

        missing: list[str] = []
        if not client_id:
            missing.append("GOOGLE_ADS_OAUTH_CLIENT_ID")
        if not client_secret:
            missing.append("GOOGLE_ADS_OAUTH_CLIENT_SECRET")
        if not refresh_token:
            missing.append("GOOGLE_ADS_OAUTH_REFRESH_TOKEN")
        missing_list = ", ".join(missing)
        raise RuntimeError(
            f"google_ads: missing environment variables: {missing_list}. "
            "Either set all three, or unset them and use gcloud ADC."
        )

    adc = _adc_credentials_path()
    if adc is None or not adc.is_file():
        raise RuntimeError(
            "google_ads: missing OAuth credentials. "
            "Set GOOGLE_ADS_OAUTH_CLIENT_ID/SECRET/REFRESH_TOKEN, "
            "or login via gcloud ADC with an OAuth client:\n"
            "  `gcloud auth application-default login --client-id-file=./client_secret.json "
            "--scopes=https://www.googleapis.com/auth/adwords`"
        )

    try:
        creds, _ = google.auth.load_credentials_from_file(
            adc, scopes=["https://www.googleapis.com/auth/adwords"]
        )
        creds.refresh(Request())
    except Exception as exc:
        raise RuntimeError(
            "google_ads: failed to load Google Ads OAuth token from gcloud ADC. "
            "Run `gcloud auth application-default login --client-id-file=./client_secret.json "
            "--scopes=https://www.googleapis.com/auth/adwords` and retry."
        ) from exc

    token = getattr(creds, "token", None)
    if not token:
        raise RuntimeError("google_ads: failed to refresh Google Ads OAuth token from gcloud ADC")
    return str(token)


def build_gaql_query(*, start_ymd: str, end_ymd: str) -> str:
    return (
        "SELECT\n"
        "  segments.date,\n"
        "  metrics.impressions,\n"
        "  metrics.clicks,\n"
        "  metrics.cost_micros\n"
        "FROM customer\n"
        f"WHERE segments.date >= '{start_ymd}'\n"
        f"  AND segments.date <= '{end_ymd}'\n"
        "ORDER BY segments.date"
    )


def search(
    *,
    api_version: str,
    customer_id: str,
    developer_token: str,
    login_customer_id: str,
    access_token: str,
    gaql: str,
) -> list[dict[str, Any]]:
    url = f"https://googleads.googleapis.com/v{api_version}/customers/{customer_id}/googleAds:search"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "developer-token": developer_token,
        "login-customer-id": login_customer_id,
        "Content-Type": "application/json",
    }

    results: list[dict[str, Any]] = []
    page_token: str | None = None
    while True:
        body: dict[str, Any] = {"query": gaql}
        if page_token:
            body["pageToken"] = page_token
        resp = request_json("POST", url, headers=headers, json_body=body)
        results.extend(resp.get("results") or [])
        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    _LOG.info("Google Ads returned %d rows", len(results))
    return results


def results_to_sheet_rows(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_date: dict[str, dict[str, float]] = defaultdict(
        lambda: {"impressions": 0.0, "clicks": 0.0, "cost_units": 0.0}
    )
    for it in items:
        if not isinstance(it, dict):
            continue
        segments = it.get("segments") if isinstance(it.get("segments"), dict) else {}
        metrics = it.get("metrics") if isinstance(it.get("metrics"), dict) else {}
        date = segments.get("date")
        if not isinstance(date, str) or not date:
            continue

        def to_int(v: Any) -> int:
            try:
                return int(v)
            except (TypeError, ValueError):
                try:
                    return int(float(v))
                except (TypeError, ValueError):
                    return 0

        def micros_to_units(v: Any) -> float:
            try:
                return float(v) / 1_000_000
            except (TypeError, ValueError):
                return 0.0

        acc = by_date[date]
        acc["impressions"] += float(to_int(metrics.get("impressions")))
        acc["clicks"] += float(to_int(metrics.get("clicks")))
        acc["cost_units"] += micros_to_units(metrics.get("costMicros"))

    rows: list[dict[str, Any]] = []
    for date in sorted(by_date.keys()):
        acc = by_date[date]
        rows.append(
            {
                "Fecha": date,
                "Impresiones": int(acc["impressions"]),
                "Visitas": int(acc["clicks"]),
                "Inversión - CLP": acc["cost_units"],
            }
        )
    return rows
