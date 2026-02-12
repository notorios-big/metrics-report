from __future__ import annotations

import logging
import math
from collections import defaultdict
from typing import Any

from metrics_report.dates import (
    daterange_inclusive,
    datetime_to_ymd_in_tz,
    parse_iso_datetime,
    parse_ymd,
)
from metrics_report.http import request_json


_LOG = logging.getLogger(__name__)


SHOPIFY_ORDERS_QUERY = """
query OrdersByDay($query: String!, $cursor: String) {
  orders(first: 250, after: $cursor, query: $query, sortKey: CREATED_AT) {
    pageInfo { hasNextPage endCursor }
    edges {
      cursor
      node {
        id
        createdAt
        email
        phone
        currentTotalDiscountsSet { shopMoney { amount currencyCode } }
        totalDiscountsSet        { shopMoney { amount currencyCode } }
        currentTotalPriceSet { shopMoney { amount currencyCode } }
        totalPriceSet        { shopMoney { amount currencyCode } }
        currentSubtotalPriceSet { shopMoney { amount currencyCode } }
        subtotalPriceSet        { shopMoney { amount currencyCode } }
        customer { id email numberOfOrders displayName firstName lastName phone }
        billingAddress { phone }
        shippingAddress { phone }
      }
    }
  }
}
"""


def _pick_money(order: dict[str, Any]) -> tuple[float, str]:
    money = (
        ((order.get("totalPriceSet") or {}).get("shopMoney"))
        or ((order.get("currentTotalPriceSet") or {}).get("shopMoney"))
        or ((order.get("subtotalPriceSet") or {}).get("shopMoney"))
        or ((order.get("currentSubtotalPriceSet") or {}).get("shopMoney"))
    )
    if not isinstance(money, dict):
        return 0.0, "CLP"
    try:
        amount = float(money.get("amount") or 0)
    except (TypeError, ValueError):
        amount = 0.0
    currency = str(money.get("currencyCode") or "CLP")
    return amount, currency


def _round_half_away_from_zero(value: float) -> int:
    if value >= 0:
        return int(math.floor(value + 0.5))
    return int(math.ceil(value - 0.5))


def _coerce_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return int(value)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            return int(stripped)
        except ValueError:
            return None
    return None


def fetch_orders(
    *,
    shop_domain: str,
    api_version: str,
    access_token: str,
    query: str,
) -> list[dict[str, Any]]:
    url = f"https://{shop_domain}/admin/api/{api_version}/graphql.json"
    headers = {"Content-Type": "application/json", "X-Shopify-Access-Token": access_token}

    cursor: str | None = None
    out: list[dict[str, Any]] = []
    while True:
        body = {"query": SHOPIFY_ORDERS_QUERY, "variables": {"query": query, "cursor": cursor}}
        resp = request_json("POST", url, headers=headers, json_body=body)
        if resp.get("errors"):
            raise RuntimeError(f"Shopify GraphQL errors: {resp['errors']}")

        orders_conn = ((resp.get("data") or {}).get("orders")) or {}
        for edge in orders_conn.get("edges") or []:
            node = (edge or {}).get("node")
            if isinstance(node, dict):
                out.append(node)

        page_info = orders_conn.get("pageInfo") or {}
        if not page_info.get("hasNextPage"):
            break
        cursor = page_info.get("endCursor")
        if not cursor:
            break

    return out


def build_shopify_search_query(*, start_ymd: str, end_ymd: str) -> str:
    return " ".join(
        [
            f"created_at:>={start_ymd}",
            f"created_at:<={end_ymd}",
            "financial_status:paid",
            "-status:cancelled",
        ]
    )


def aggregate_orders_to_rows(
    *,
    orders: list[dict[str, Any]],
    start_ymd: str,
    end_ymd: str,
    timezone: str,
    fixed_deduction_per_order: int = 0,
    vat_factor: float = 1.19,
) -> list[dict[str, Any]]:
    start_date = parse_ymd(start_ymd)
    end_date = parse_ymd(end_ymd)
    if not start_date or not end_date:
        raise ValueError("Invalid start/end date")

    by_day: dict[str, dict[str, float]] = defaultdict(
        lambda: {
            "orders_new": 0.0,
            "orders_returning": 0.0,
            "revenue_new_raw": 0.0,
            "revenue_returning_raw": 0.0,
        }
    )

    for order in orders:
        created_at = order.get("createdAt")
        if not isinstance(created_at, str) or not created_at:
            continue

        date_key = datetime_to_ymd_in_tz(parse_iso_datetime(created_at), timezone)
        amount, _currency = _pick_money(order)

        customer = order.get("customer") if isinstance(order.get("customer"), dict) else None
        num_orders = customer.get("numberOfOrders") if customer else None
        num_orders_int = _coerce_int(num_orders)
        is_returning = bool(num_orders_int is not None and num_orders_int >= 2)
        cohort = "returning" if is_returning else "new"

        acc = by_day[date_key]
        if cohort == "returning":
            acc["orders_returning"] += 1
            acc["revenue_returning_raw"] += amount
        else:
            acc["orders_new"] += 1
            acc["revenue_new_raw"] += amount

    rows: list[dict[str, Any]] = []
    for day in daterange_inclusive(start_date, end_date):
        key = day.isoformat()
        acc = by_day.get(key) or {
            "orders_new": 0.0,
            "orders_returning": 0.0,
            "revenue_new_raw": 0.0,
            "revenue_returning_raw": 0.0,
        }

        orders_new = int(acc["orders_new"])
        orders_returning = int(acc["orders_returning"])
        revenue_new_raw = float(acc["revenue_new_raw"])
        revenue_returning_raw = float(acc["revenue_returning_raw"])

        revenue_new = _round_half_away_from_zero((revenue_new_raw - fixed_deduction_per_order * orders_new) / vat_factor)
        revenue_returning = _round_half_away_from_zero(
            (revenue_returning_raw - fixed_deduction_per_order * orders_returning) / vat_factor
        )

        rows.append(
            {
                "Día": key,
                "orders_new": orders_new,
                "orders_returning": orders_returning,
                "revenue_new": revenue_new,
                "revenue_returning": revenue_returning,
            }
        )

    _LOG.info("Shopify aggregated %d day rows", len(rows))
    return rows


SHOPIFY_FUNNEL_QUERY = """
query ShopifyFunnel($query: String!) {
  shopifyqlQuery(query: $query) {
    __typename
    ... on TableResponse {
      tableData {
        columns { name dataType displayName }
        rowData
        unformattedData
      }
    }
    parseErrors {
      code
      message
    }
  }
}
"""


def fetch_funnel_by_day(
    *,
    shop_domain: str,
    api_version: str,
    access_token: str,
    start_ymd: str,
    end_ymd: str,
) -> list[dict[str, Any]]:
    url = f"https://{shop_domain}/admin/api/{api_version}/graphql.json"
    headers = {"Content-Type": "application/json", "X-Shopify-Access-Token": access_token}

    shopifyql = (
        "FROM products "
        "SHOW sum(view_cart_sessions) AS add_to_cart, "
        "sum(view_cart_checkout_sessions) AS begin_checkout, "
        "sum(view_cart_checkout_purchase_sessions) AS purchase "
        f"GROUP BY day SINCE {start_ymd} UNTIL {end_ymd} ORDER BY day ASC"
    )

    body = {"query": SHOPIFY_FUNNEL_QUERY, "variables": {"query": shopifyql}}
    resp = request_json("POST", url, headers=headers, json_body=body)
    if resp.get("errors"):
        raise RuntimeError(f"Shopify GraphQL errors: {resp['errors']}")

    ql_resp = (resp.get("data") or {}).get("shopifyqlQuery") or {}

    parse_errors = ql_resp.get("parseErrors")
    if parse_errors:
        raise RuntimeError(f"ShopifyQL parse errors: {parse_errors}")

    table_data = (ql_resp.get("tableData") or {})
    columns = table_data.get("columns") or []
    col_names = [c.get("name", "") for c in columns]
    raw_rows = table_data.get("unformattedData") or table_data.get("rowData") or []

    out: list[dict[str, Any]] = []
    for row in raw_rows:
        record: dict[str, Any] = {}
        for i, val in enumerate(row):
            if i < len(col_names):
                record[col_names[i]] = val
        out.append(record)

    _LOG.info("ShopifyQL funnel returned %d day rows", len(out))
    return out


def funnel_to_sheet_rows(funnel_data: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for entry in funnel_data:
        day = str(entry.get("day", ""))
        if not day:
            continue
        # Strip time component if present (e.g. "2025-01-15T00:00:00" -> "2025-01-15")
        day = day[:10]
        rows.append(
            {
                "Día": day,
                "Add to cart": int(entry.get("add_to_cart", 0) or 0),
                "Begin Checkout": int(entry.get("begin_checkout", 0) or 0),
                "Purchase": int(entry.get("purchase", 0) or 0),
            }
        )
    return rows
