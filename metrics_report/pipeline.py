from __future__ import annotations

import logging

from metrics_report.config import AppConfig
from metrics_report.customers import sync_consolidado_customers
from metrics_report.dates import add_days, parse_ymd, yesterday_ymd
from metrics_report.google_ads import (
    build_gaql_query,
    get_access_token as get_google_ads_access_token,
    results_to_sheet_rows as google_ads_rows,
    search as google_ads_search,
)
from metrics_report.klaviyo import (
    build_metric_aggregates_body,
    fetch_metric_aggregates,
    metric_aggregates_to_sheet_rows,
)
from metrics_report.meta_ads import (
    ad_insights_to_sheet_rows,
    fetch_account_insights_by_day,
    fetch_ad_insights_by_day,
    insights_to_sheet_rows,
)
from metrics_report.sheets import GoogleSheetsClient
from metrics_report.shopify import (
    aggregate_orders_to_rows,
    build_shopify_search_query,
    fetch_orders,
)


_LOG = logging.getLogger(__name__)


def _require_max_date(sheet_name: str, max_date: str | None) -> str:
    if not max_date:
        raise RuntimeError(f"Could not determine last saved date for sheet '{sheet_name}'")
    return max_date


def _require_ymd(label: str, value: str) -> str:
    if not parse_ymd(value):
        raise RuntimeError(f"Invalid date for {label}: {value!r}")
    return value


def _require_env(task: str, env_name: str, value: str) -> str:
    if not value:
        raise RuntimeError(f"{task}: missing environment variable {env_name}")
    return value


def run_pipeline(config: AppConfig, *, only: set[str] | None = None, dry_run: bool = False) -> None:
    sheets = GoogleSheetsClient(config.sheets.spreadsheet_id)
    last_date = _require_ymd("last_date", yesterday_ymd(config.timezone))
    errors: list[Exception] = []

    def enabled(task: str) -> bool:
        return only is None or task in only

    sheet_to_check: str | None = None
    if enabled("shopify"):
        sheet_to_check = config.sheets.purchase_sheet
    elif enabled("meta"):
        sheet_to_check = config.sheets.meta_sheet
    elif enabled("meta_ads"):
        sheet_to_check = config.sheets.ads_sheet
    elif enabled("google_ads"):
        sheet_to_check = config.sheets.gads_sheet
    elif enabled("klaviyo"):
        sheet_to_check = config.sheets.klaviyo_sheet
    if sheet_to_check:
        sheets.get_header(sheet_to_check)

    if enabled("shopify"):
        try:
            max_info = sheets.get_max_ymd_in_column(
                config.sheets.purchase_sheet,
                date_headers=["Día", "Dia", "dia", "Fecha", "date"],
            )
            max_saved = _require_max_date(config.sheets.purchase_sheet, max_info.max_date)
            max_saved_date = parse_ymd(max_saved)
            if not max_saved_date:
                raise RuntimeError(f"Invalid date in sheet '{config.sheets.purchase_sheet}': {max_saved!r}")
            start = add_days(max_saved_date, 1).isoformat()
            end = _require_ymd("shopify end", last_date)
            if start > end:
                _LOG.info("Shopify: nothing to do (start=%s end=%s)", start, end)
            else:
                query = build_shopify_search_query(start_ymd=start, end_ymd=end)
                orders = fetch_orders(
                    shop_domain=config.shopify.shop_domain,
                    api_version=config.shopify.api_version,
                    access_token=_require_env("shopify", "SHOPIFY_ACCESS_TOKEN", config.shopify.access_token),
                    query=query,
                )
                rows = aggregate_orders_to_rows(
                    orders=orders,
                    start_ymd=start,
                    end_ymd=end,
                    timezone=config.timezone,
                    fixed_deduction_per_order=config.shopify.fixed_deduction_per_order,
                    vat_factor=config.shopify.vat_factor,
                )
                if dry_run:
                    _LOG.info("Shopify: dry-run, would append %d rows", len(rows))
                else:
                    sheets.append_rows(config.sheets.purchase_sheet, header=max_info.header, rows=rows)
                    _LOG.info("Shopify: appended %d rows", len(rows))
        except Exception as e:
            _LOG.exception("Shopify task failed")
            errors.append(e)

    if enabled("customers"):
        try:
            _require_env("customers", "SHOPIFY_ACCESS_TOKEN", config.shopify.access_token)
            sync_consolidado_customers(config, end_ymd=last_date, dry_run=dry_run)
        except Exception as e:
            _LOG.exception("Customers task failed")
            errors.append(e)

    if enabled("meta"):
        try:
            max_info = sheets.get_max_ymd_in_column(config.sheets.meta_sheet, date_headers=["Fecha", "Día", "Dia"])
            max_saved = _require_max_date(config.sheets.meta_sheet, max_info.max_date)
            max_saved_date = parse_ymd(max_saved)
            if not max_saved_date:
                raise RuntimeError(f"Invalid date in sheet '{config.sheets.meta_sheet}': {max_saved!r}")
            start = add_days(max_saved_date, 1).isoformat()
            end = _require_ymd("meta end", last_date)
            if start > end:
                _LOG.info("Meta: nothing to do (start=%s end=%s)", start, end)
            else:
                insights = fetch_account_insights_by_day(
                    api_version=config.meta.api_version,
                    ad_account_id=config.meta.ad_account_id,
                    access_token=_require_env("meta", "META_ACCESS_TOKEN", config.meta.access_token),
                    since_ymd=start,
                    until_ymd=end,
                )
                rows = insights_to_sheet_rows(insights)
                if dry_run:
                    _LOG.info("Meta: dry-run, would append %d rows", len(rows))
                else:
                    sheets.append_rows(config.sheets.meta_sheet, header=max_info.header, rows=rows)
                    _LOG.info("Meta: appended %d rows", len(rows))
        except Exception as e:
            _LOG.exception("Meta task failed")
            errors.append(e)

    if enabled("meta_ads"):
        try:
            max_info = sheets.get_max_ymd_in_column(config.sheets.ads_sheet, date_headers=["Fecha", "Día", "Dia"])
            if max_info.max_date:
                max_saved_date = parse_ymd(max_info.max_date)
                if not max_saved_date:
                    raise RuntimeError(f"Invalid date in sheet '{config.sheets.ads_sheet}': {max_info.max_date!r}")
                start = add_days(max_saved_date, 1).isoformat()
            else:
                start = "2025-11-01"
                _LOG.info("Meta Ads: empty sheet, backfilling from %s", start)
            end = _require_ymd("meta_ads end", last_date)
            if start > end:
                _LOG.info("Meta Ads: nothing to do (start=%s end=%s)", start, end)
            else:
                ad_insights = fetch_ad_insights_by_day(
                    api_version=config.meta.api_version,
                    ad_account_id=config.meta.ad_account_id,
                    access_token=_require_env("meta_ads", "META_ACCESS_TOKEN", config.meta.access_token),
                    since_ymd=start,
                    until_ymd=end,
                )
                rows = ad_insights_to_sheet_rows(ad_insights)
                if dry_run:
                    _LOG.info("Meta Ads: dry-run, would append %d rows", len(rows))
                else:
                    sheets.append_rows(config.sheets.ads_sheet, header=max_info.header, rows=rows)
                    _LOG.info("Meta Ads: appended %d rows", len(rows))
        except Exception as e:
            _LOG.exception("Meta Ads task failed")
            errors.append(e)

    if enabled("google_ads"):
        try:
            max_info = sheets.get_max_ymd_in_column(config.sheets.gads_sheet, date_headers=["Fecha", "Día", "Dia"])
            max_saved = _require_max_date(config.sheets.gads_sheet, max_info.max_date)
            max_saved_date = parse_ymd(max_saved)
            if not max_saved_date:
                raise RuntimeError(f"Invalid date in sheet '{config.sheets.gads_sheet}': {max_saved!r}")
            start = add_days(max_saved_date, 1).isoformat()
            end = _require_ymd("google_ads end", last_date)
            if start > end:
                _LOG.info("Google Ads: nothing to do (start=%s end=%s)", start, end)
            else:
                _require_env("google_ads", "GOOGLE_ADS_DEVELOPER_TOKEN", config.google_ads.developer_token)
                access_token = get_google_ads_access_token(
                    client_id=config.google_ads.oauth_client_id,
                    client_secret=config.google_ads.oauth_client_secret,
                    refresh_token=config.google_ads.oauth_refresh_token,
                )
                gaql = build_gaql_query(start_ymd=start, end_ymd=end)
                results = google_ads_search(
                    api_version=config.google_ads.api_version,
                    customer_id=config.google_ads.customer_id,
                    developer_token=config.google_ads.developer_token,
                    login_customer_id=config.google_ads.login_customer_id,
                    access_token=access_token,
                    gaql=gaql,
                )
                rows = google_ads_rows(results)
                if dry_run:
                    _LOG.info("Google Ads: dry-run, would append %d rows", len(rows))
                else:
                    sheets.append_rows(config.sheets.gads_sheet, header=max_info.header, rows=rows)
                    _LOG.info("Google Ads: appended %d rows", len(rows))
        except Exception as e:
            _LOG.exception("Google Ads task failed")
            errors.append(e)

    if enabled("klaviyo"):
        try:
            if not dry_run:
                merged = sheets.consolidate_sum_by_date(
                    config.sheets.klaviyo_sheet,
                    date_headers=["Fecha", "Día", "Dia"],
                    sum_headers=["Suscriptores"],
                )
                if merged:
                    _LOG.info("Klaviyo: consolidated %d duplicate row(s) in sheet", merged)

            max_info = sheets.get_max_ymd_in_column(config.sheets.klaviyo_sheet, date_headers=["Fecha", "Día", "Dia"])
            max_saved = _require_max_date(config.sheets.klaviyo_sheet, max_info.max_date)
            max_saved_date = parse_ymd(max_saved)
            if not max_saved_date:
                raise RuntimeError(f"Invalid date in sheet '{config.sheets.klaviyo_sheet}': {max_saved!r}")
            last_date_obj = parse_ymd(last_date)
            if not last_date_obj:
                raise RuntimeError(f"Invalid last_date: {last_date!r}")
            start = add_days(max_saved_date, 1).isoformat()
            end_exclusive = add_days(last_date_obj, 1).isoformat()
            if start >= end_exclusive:
                _LOG.info("Klaviyo: nothing to do (start=%s end_exclusive=%s)", start, end_exclusive)
            else:
                body = build_metric_aggregates_body(
                    metric_id=config.klaviyo.metric_id,
                    start_ymd=start,
                    end_exclusive_ymd=end_exclusive,
                    timezone=config.timezone,
                    by=config.klaviyo.by,
                )
                private_key = _require_env("klaviyo", "KLAVIYO_PRIVATE_KEY", config.klaviyo.private_key)
                resp = fetch_metric_aggregates(private_key=private_key, revision=config.klaviyo.revision, body=body)
                rows = metric_aggregates_to_sheet_rows(resp)
                rows = [r for r in rows if r.get("Fecha", "") > max_saved]
                if dry_run:
                    _LOG.info("Klaviyo: dry-run, would append %d rows", len(rows))
                else:
                    if rows:
                        sheets.append_rows(config.sheets.klaviyo_sheet, header=max_info.header, rows=rows)
                    _LOG.info("Klaviyo: appended %d rows", len(rows))
        except Exception as e:
            _LOG.exception("Klaviyo task failed")
            errors.append(e)

    if errors:
        raise RuntimeError(f"Pipeline finished with {len(errors)} error(s)") from errors[0]
