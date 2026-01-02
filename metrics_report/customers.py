from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from metrics_report.config import AppConfig
from metrics_report.dates import add_days, datetime_to_ymd_in_tz, parse_iso_datetime, parse_ymd
from metrics_report.sheets import GoogleSheetsClient, _coerce_cell_to_ymd, _col_letter
from metrics_report.shopify import (
    _pick_money,
    _round_half_away_from_zero,
    build_shopify_search_query,
    fetch_orders,
)


_LOG = logging.getLogger(__name__)

@dataclass
class CustomerAggregate:
    email: str
    name: str = ""
    phone: str = ""
    total_orders: int = 0
    discounted_orders: int = 0
    money_units: float = 0.0
    last_purchase_ymd: str | None = None


SENSITIVITY_COLUMN = "Sensibilidad a descuento (Alta +80%, Media 60%, Baja 40%)"
DEFAULT_CONSOLIDADO_HEADER: list[str] = [
    "Nombre",
    "Email",
    "Teléfono",
    "Frecuency",
    "Recency",
    "Money",
    SENSITIVITY_COLUMN,
    "Buy_reason",
    "Occasion_trigger",
    "Desired_outcome",
]
INTERNAL_COLUMNS: list[str] = [
    "__last_purchase_ymd",
    "__discounted_orders",
    "__total_orders",
    "__money_units",
]


def _normalize_email(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    email = value.strip().lower()
    if not email:
        return None
    return email


def _normalize_header(value: Any) -> str:
    return str(value or "").strip().lower()


def _find_header_idx(
    header: list[Any],
    name: str,
    *,
    aliases: tuple[str, ...] = (),
    prefix: bool = False,
) -> int | None:
    wanted = [_normalize_header(name), *(_normalize_header(a) for a in aliases)]
    for idx, raw in enumerate(header):
        cell = _normalize_header(raw)
        if not cell:
            continue
        for w in wanted:
            if not w:
                continue
            if cell == w or (prefix and cell.startswith(w)):
                return idx
    return None


def _coerce_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value != value:  # NaN
            return None
        return int(value)
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        digits = re.sub(r"[^0-9-]", "", s)
        if not digits or digits == "-":
            return None
        try:
            return int(digits)
        except ValueError:
            return None
    return None


def _coerce_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        out = float(value)
        if out != out:  # NaN
            return None
        return out
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        # Remove currency symbols and keep digits/separators.
        cleaned = re.sub(r"[^0-9,.-]", "", s)
        if not cleaned or cleaned in {"-", ".", ","}:
            return None
        # Handle locales: if both '.' and ',' exist, assume ',' is thousands separator.
        if "." in cleaned and "," in cleaned:
            cleaned = cleaned.replace(",", "")
        # If only ',' exists, treat it as decimal separator.
        elif "," in cleaned and "." not in cleaned:
            cleaned = cleaned.replace(",", ".")
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


def _pick_discount_amount(order: dict[str, Any]) -> float:
    money = (
        ((order.get("currentTotalDiscountsSet") or {}).get("shopMoney"))
        or ((order.get("totalDiscountsSet") or {}).get("shopMoney"))
    )
    if not isinstance(money, dict):
        return 0.0
    try:
        return float(money.get("amount") or 0)
    except (TypeError, ValueError):
        return 0.0


def _pick_customer_email(order: dict[str, Any]) -> str | None:
    customer = order.get("customer") if isinstance(order.get("customer"), dict) else {}
    email = customer.get("email") or order.get("email")
    return _normalize_email(email)


def _pick_customer_name(order: dict[str, Any]) -> str:
    customer = order.get("customer") if isinstance(order.get("customer"), dict) else {}
    display = customer.get("displayName")
    if isinstance(display, str) and display.strip():
        return display.strip()

    first = customer.get("firstName")
    last = customer.get("lastName")
    parts = [p.strip() for p in (first, last) if isinstance(p, str) and p.strip()]
    if parts:
        return " ".join(parts)
    return ""


def _pick_customer_phone(order: dict[str, Any]) -> str:
    customer = order.get("customer") if isinstance(order.get("customer"), dict) else {}
    for candidate in (
        customer.get("phone"),
        order.get("phone"),
        (order.get("shippingAddress") or {}).get("phone") if isinstance(order.get("shippingAddress"), dict) else None,
        (order.get("billingAddress") or {}).get("phone") if isinstance(order.get("billingAddress"), dict) else None,
    ):
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return ""


def _ensure_consolidado_header(sheets: GoogleSheetsClient, sheet_name: str) -> tuple[list[str], bool]:
    existing = sheets.get_header(sheet_name)
    if not existing:
        header = [*DEFAULT_CONSOLIDADO_HEADER, *INTERNAL_COLUMNS]
        sheets.update_values(sheet_name, "A1", values=[header])
        return header, True

    header = list(existing)
    changed = False

    required = [
        ("Nombre", (), False),
        ("Email", (), False),
        ("Teléfono", ("Telefono",), False),
        ("Frecuency", (), False),
        ("Recency", (), False),
        ("Money", (), False),
        (SENSITIVITY_COLUMN, ("Sensibilidad a descuento",), True),
    ]

    for name, aliases, prefix in required:
        if _find_header_idx(header, name, aliases=aliases, prefix=prefix) is None:
            header.append(name)
            changed = True

    internal_missing = False
    for name in INTERNAL_COLUMNS:
        if _find_header_idx(header, name) is None:
            header.append(name)
            changed = True
            internal_missing = True

    if changed:
        sheets.update_values(sheet_name, "A1", values=[header])

    return header, internal_missing


def sync_consolidado_customers(config: AppConfig, *, end_ymd: str, dry_run: bool = False) -> None:
    consolidated = GoogleSheetsClient(config.sheets.customers_spreadsheet_id)
    sheet_name = config.sheets.customers_sheet
    header, internal_added = _ensure_consolidado_header(consolidated, sheet_name)

    email_idx = _find_header_idx(header, "Email")
    if email_idx is None:
        raise ValueError(f"Sheet '{sheet_name}' missing column 'Email'")

    freq_idx = _find_header_idx(header, "Frecuency")
    recency_idx = _find_header_idx(header, "Recency")
    money_idx = _find_header_idx(header, "Money")
    sensitivity_idx = _find_header_idx(header, SENSITIVITY_COLUMN, aliases=("Sensibilidad a descuento",), prefix=True)

    last_idx = _find_header_idx(header, "__last_purchase_ymd")
    discounted_idx = _find_header_idx(header, "__discounted_orders")
    total_idx = _find_header_idx(header, "__total_orders")
    money_units_idx = _find_header_idx(header, "__money_units")

    missing_required = [
        name
        for name, idx in [
            ("Frecuency", freq_idx),
            ("Recency", recency_idx),
            ("Money", money_idx),
            (SENSITIVITY_COLUMN, sensitivity_idx),
            ("__last_purchase_ymd", last_idx),
            ("__discounted_orders", discounted_idx),
            ("__total_orders", total_idx),
            ("__money_units", money_units_idx),
        ]
        if idx is None
    ]
    if missing_required:
        raise ValueError(f"Sheet '{sheet_name}' missing required columns: {', '.join(missing_required)}")

    last_letter = _col_letter(len(header) - 1)
    values = consolidated.get_values(
        sheet_name,
        f"A1:{last_letter}",
        value_render_option="UNFORMATTED_VALUE",
        date_time_render_option="SERIAL_NUMBER",
    )

    data_rows = max(0, len(values) - 1)
    row_emails: list[str | None] = []
    emails_in_sheet: set[str] = set()
    max_last: str | None = None

    def cell(row: list[Any], idx: int) -> Any:
        return row[idx] if idx < len(row) else ""

    aggregates: dict[str, CustomerAggregate] = {}
    if not internal_added:
        for row in values[1:]:
            email = _normalize_email(cell(row, email_idx))
            row_emails.append(email)
            if not email:
                continue
            emails_in_sheet.add(email)

            total = _coerce_int(cell(row, total_idx)) or _coerce_int(cell(row, freq_idx)) or 0
            discounted = _coerce_int(cell(row, discounted_idx)) or 0
            raw_units = _coerce_float(cell(row, money_units_idx))
            if raw_units is None:
                raw_units = _coerce_float(cell(row, money_idx)) or 0.0
            last_ymd = _coerce_cell_to_ymd(cell(row, last_idx))
            if last_ymd and (max_last is None or last_ymd > max_last):
                max_last = last_ymd

            agg = aggregates.get(email)
            if agg is None:
                agg = CustomerAggregate(email=email)
                aggregates[email] = agg

            agg.total_orders = max(agg.total_orders, int(total))
            agg.discounted_orders = max(agg.discounted_orders, int(discounted))
            agg.money_units = max(agg.money_units, float(raw_units))
            if last_ymd and (agg.last_purchase_ymd is None or last_ymd > agg.last_purchase_ymd):
                agg.last_purchase_ymd = last_ymd
    else:
        for row in values[1:]:
            email = _normalize_email(cell(row, email_idx))
            row_emails.append(email)
            if email:
                emails_in_sheet.add(email)

    needs_backfill = internal_added or max_last is None
    if needs_backfill:
        aggregates = {}

    start_ymd: str | None = None
    if not needs_backfill and max_last:
        max_last_date = parse_ymd(max_last)
        if max_last_date:
            start_ymd = add_days(max_last_date, 1).isoformat()

    orders: list[dict[str, Any]] = []
    if start_ymd and start_ymd > end_ymd:
        _LOG.info("Customers: nothing to fetch (start=%s end=%s)", start_ymd, end_ymd)
    else:
        if start_ymd:
            query = build_shopify_search_query(start_ymd=start_ymd, end_ymd=end_ymd)
        else:
            query = " ".join([f"created_at:<={end_ymd}", "financial_status:paid", "-status:cancelled"])

        orders = fetch_orders(
            shop_domain=config.shopify.shop_domain,
            api_version=config.shopify.api_version,
            access_token=config.shopify.access_token,
            query=query,
        )

    for order in orders:
        email = _pick_customer_email(order)
        if not email:
            continue

        created_at = order.get("createdAt")
        if not isinstance(created_at, str) or not created_at:
            continue

        day = datetime_to_ymd_in_tz(parse_iso_datetime(created_at), config.timezone)
        amount, _currency = _pick_money(order)
        discount_amount = _pick_discount_amount(order)
        net_units = (amount - float(config.shopify.fixed_deduction_per_order)) / float(config.shopify.vat_factor)

        agg = aggregates.get(email)
        if agg is None:
            agg = CustomerAggregate(email=email)
            aggregates[email] = agg

        agg.total_orders += 1
        if discount_amount > 0:
            agg.discounted_orders += 1
        agg.money_units += float(net_units)
        if agg.last_purchase_ymd is None or day > agg.last_purchase_ymd:
            agg.last_purchase_ymd = day

        if not agg.name:
            agg.name = _pick_customer_name(order)
        if not agg.phone:
            agg.phone = _pick_customer_phone(order)

    end_date = parse_ymd(end_ymd)
    if not end_date:
        raise ValueError(f"Invalid end_ymd: {end_ymd!r}")

    def sensitivity_label(*, discounted_orders: int, total_orders: int) -> str:
        if total_orders <= 0:
            return ""
        ratio = discounted_orders / float(total_orders)
        if ratio >= 0.8:
            return "Alta"
        if ratio >= 0.6:
            return "Media"
        return "Baja"

    updates_by_email: dict[str, dict[int, Any]] = {}
    for email, agg in aggregates.items():
        if not agg.last_purchase_ymd:
            continue
        last_date = parse_ymd(agg.last_purchase_ymd)
        if not last_date:
            continue
        recency_days = (end_date - last_date).days
        updates_by_email[email] = {
            freq_idx: int(agg.total_orders),
            recency_idx: int(recency_days),
            money_idx: _round_half_away_from_zero(float(agg.money_units)),
            sensitivity_idx: sensitivity_label(
                discounted_orders=int(agg.discounted_orders),
                total_orders=int(agg.total_orders),
            ),
            last_idx: agg.last_purchase_ymd,
            discounted_idx: int(agg.discounted_orders),
            total_idx: int(agg.total_orders),
            money_units_idx: round(float(agg.money_units), 6),
        }

    if dry_run:
        to_update = sum(1 for email in emails_in_sheet if email in updates_by_email)
        to_append = sum(1 for email in updates_by_email.keys() if email not in emails_in_sheet)
        _LOG.info(
            "Customers: dry-run, would update %d existing row(s) and append %d new customer(s) to %s",
            to_update,
            to_append,
            sheet_name,
        )
        return

    if data_rows:
        update_cols = sorted({*updates_by_email[next(iter(updates_by_email))].keys()} if updates_by_email else set())
        groups: list[list[int]] = []
        for idx in update_cols:
            if not groups or idx != groups[-1][-1] + 1:
                groups.append([idx])
            else:
                groups[-1].append(idx)

        batch_updates: list[tuple[str, list[list[Any]]]] = []
        for group in groups:
            start_col = _col_letter(group[0])
            end_col = _col_letter(group[-1])
            a1_range = (
                f"{start_col}2:{end_col}{data_rows + 1}"
                if start_col != end_col
                else f"{start_col}2:{start_col}{data_rows + 1}"
            )
            matrix: list[list[Any]] = []
            for row_idx in range(data_rows):
                row = values[row_idx + 1] if row_idx + 1 < len(values) else []
                email = row_emails[row_idx] if row_idx < len(row_emails) else None
                row_updates = updates_by_email.get(email or "")
                out_row: list[Any] = []
                for col_idx in group:
                    if row_updates and col_idx in row_updates:
                        out_row.append(row_updates[col_idx])
                    else:
                        out_row.append(cell(row, col_idx))
                matrix.append(out_row)
            batch_updates.append((a1_range, matrix))

        if batch_updates:
            consolidated.batch_update_values(sheet_name, updates=batch_updates)

    new_rows: list[dict[str, Any]] = []
    name_idx = _find_header_idx(header, "Nombre")
    phone_idx = _find_header_idx(header, "Teléfono", aliases=("Telefono",))
    for email, updates in sorted(updates_by_email.items(), key=lambda kv: kv[0]):
        if email in emails_in_sheet:
            continue
        agg = aggregates.get(email)
        if agg is None:
            continue
        row: dict[str, Any] = {}
        if name_idx is not None:
            row[header[name_idx]] = agg.name
        row[header[email_idx]] = email
        if phone_idx is not None:
            row[header[phone_idx]] = agg.phone
        row[header[freq_idx]] = updates.get(freq_idx, "")
        row[header[recency_idx]] = updates.get(recency_idx, "")
        row[header[money_idx]] = updates.get(money_idx, "")
        row[header[sensitivity_idx]] = updates.get(sensitivity_idx, "")
        row[header[last_idx]] = updates.get(last_idx, "")
        row[header[discounted_idx]] = updates.get(discounted_idx, "")
        row[header[total_idx]] = updates.get(total_idx, "")
        row[header[money_units_idx]] = updates.get(money_units_idx, "")
        new_rows.append(row)

    if new_rows:
        consolidated.append_rows(sheet_name, header=header, rows=new_rows)

    _LOG.info(
        "Customers: updated %d existing row(s), appended %d new customer(s) to %s",
        sum(1 for email in emails_in_sheet if email in updates_by_email),
        len(new_rows),
        sheet_name,
    )
