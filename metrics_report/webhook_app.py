from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os

from fastapi import FastAPI, Header, Request, Response

from metrics_report.dates import datetime_to_ymd_in_tz, parse_iso_datetime
from metrics_report.webhook_db import cleanup_old_carts, increment, try_record_cart

_LOG = logging.getLogger(__name__)

app = FastAPI(docs_url=None, redoc_url=None)

_TIMEZONE = os.getenv("REPORT_TIMEZONE", "America/Santiago")
_DB_PATH = os.getenv("WEBHOOK_DB_PATH", "webhooks.db")
_SECRET = os.getenv("SHOPIFY_WEBHOOK_SECRET", "")


def _verify_hmac(body: bytes, header_hmac: str) -> bool:
    if not _SECRET:
        _LOG.warning("SHOPIFY_WEBHOOK_SECRET not set, skipping HMAC verification")
        return True
    digest = hmac.new(_SECRET.encode(), body, hashlib.sha256).digest()
    expected = base64.b64encode(digest).decode()
    return hmac.compare_digest(expected, header_hmac)


def _extract_date(payload: dict) -> str:
    ts = payload.get("created_at") or payload.get("updated_at") or ""
    if not ts:
        from metrics_report.dates import today_in_tz

        return today_in_tz(_TIMEZONE).isoformat()
    return datetime_to_ymd_in_tz(parse_iso_datetime(ts), _TIMEZONE)


@app.post("/carts_created")
async def carts_created(
    request: Request,
    x_shopify_hmac_sha256: str = Header(""),
) -> Response:
    body = await request.body()
    if not _verify_hmac(body, x_shopify_hmac_sha256):
        return Response(status_code=401)

    try:
        payload = await request.json()
    except Exception:
        return Response(status_code=400)

    cart_token = str(payload.get("token") or payload.get("id") or "")
    if not cart_token:
        return Response(status_code=200)

    date = _extract_date(payload)
    if try_record_cart(_DB_PATH, cart_token, date):
        increment(_DB_PATH, date, "add_to_cart")
        _LOG.info("add_to_cart: new cart %s on %s", cart_token[:8], date)

    return Response(status_code=200)


@app.post("/checkout_created")
async def checkout_created(
    request: Request,
    x_shopify_hmac_sha256: str = Header(""),
) -> Response:
    body = await request.body()
    if not _verify_hmac(body, x_shopify_hmac_sha256):
        return Response(status_code=401)

    try:
        payload = await request.json()
    except Exception:
        return Response(status_code=400)

    date = _extract_date(payload)
    increment(_DB_PATH, date, "begin_checkout")
    _LOG.info("begin_checkout on %s", date)
    return Response(status_code=200)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.on_event("startup")
async def _startup_cleanup() -> None:
    from metrics_report.dates import add_days, today_in_tz

    cutoff = add_days(today_in_tz(_TIMEZONE), -7).isoformat()
    deleted = cleanup_old_carts(_DB_PATH, cutoff)
    if deleted:
        _LOG.info("Cleaned up %d old cart tokens (before %s)", deleted, cutoff)
