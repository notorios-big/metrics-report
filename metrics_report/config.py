from __future__ import annotations

import os
from dataclasses import dataclass


_ENV_PREFIXES: tuple[str, ...] = ("LEJUSTE_", "")


def _env(name: str, *, default: str | None = None) -> str | None:
    for prefix in _ENV_PREFIXES:
        key = f"{prefix}{name}" if prefix else name
        value = os.getenv(key)
        if value is None:
            continue
        value = value.strip()
        return value or default
    return default


def _required(name: str) -> str:
    value = _env(name)
    if value is None:
        raise ValueError(f"Missing required environment variable: LEJUSTE_{name} (or {name})")
    return value


@dataclass(frozen=True)
class SheetsConfig:
    spreadsheet_id: str = "1h1_rGZEncDj8WRLnf4m9Kqr-78JGqoxq0CH_WnIzdH8"
    purchase_sheet: str = "PURCHASE"
    meta_sheet: str = "META"
    gads_sheet: str = "GADS"
    klaviyo_sheet: str = "KLAVIYO"


@dataclass(frozen=True)
class ShopifyConfig:
    shop_domain: str = "le-juste-s.myshopify.com"
    api_version: str = "2024-10"
    access_token: str = ""


@dataclass(frozen=True)
class MetaConfig:
    api_version: str = "v23.0"
    ad_account_id: str = "act_1219778112947622"
    access_token: str = ""


@dataclass(frozen=True)
class GoogleAdsConfig:
    api_version: str = "21"
    customer_id: str = "3261990482"
    login_customer_id: str = "8058839890"
    developer_token: str = ""
    oauth_client_id: str = ""
    oauth_client_secret: str = ""
    oauth_refresh_token: str = ""


@dataclass(frozen=True)
class KlaviyoConfig:
    revision: str = "2025-07-15"
    metric_id: str = "XvmGgm"
    by: tuple[str, ...] = ()
    private_key: str = ""


@dataclass(frozen=True)
class AppConfig:
    timezone: str = "America/Santiago"
    sheets: SheetsConfig = SheetsConfig()
    shopify: ShopifyConfig = ShopifyConfig()
    meta: MetaConfig = MetaConfig()
    google_ads: GoogleAdsConfig = GoogleAdsConfig()
    klaviyo: KlaviyoConfig = KlaviyoConfig()


def load_config() -> AppConfig:
    sheets = SheetsConfig(
        spreadsheet_id=_env("GOOGLE_SHEETS_SPREADSHEET_ID", default=SheetsConfig.spreadsheet_id)
        or SheetsConfig.spreadsheet_id,
        purchase_sheet=_env("GOOGLE_SHEETS_PURCHASE_SHEET", default=SheetsConfig.purchase_sheet)
        or SheetsConfig.purchase_sheet,
        meta_sheet=_env("GOOGLE_SHEETS_META_SHEET", default=SheetsConfig.meta_sheet)
        or SheetsConfig.meta_sheet,
        gads_sheet=_env("GOOGLE_SHEETS_GADS_SHEET", default=SheetsConfig.gads_sheet) or SheetsConfig.gads_sheet,
        klaviyo_sheet=_env("GOOGLE_SHEETS_KLAVIYO_SHEET", default=SheetsConfig.klaviyo_sheet)
        or SheetsConfig.klaviyo_sheet,
    )

    shopify = ShopifyConfig(
        shop_domain=_env("SHOPIFY_SHOP_DOMAIN", default=ShopifyConfig.shop_domain) or ShopifyConfig.shop_domain,
        api_version=_env("SHOPIFY_API_VERSION", default=ShopifyConfig.api_version) or ShopifyConfig.api_version,
        access_token=_env("SHOPIFY_ACCESS_TOKEN", default="") or "",
    )

    meta = MetaConfig(
        api_version=_env("META_API_VERSION", default=MetaConfig.api_version) or MetaConfig.api_version,
        ad_account_id=_env("META_AD_ACCOUNT_ID", default=MetaConfig.ad_account_id) or MetaConfig.ad_account_id,
        access_token=_env("META_ACCESS_TOKEN", default="") or "",
    )

    google_ads = GoogleAdsConfig(
        api_version=_env("GOOGLE_ADS_API_VERSION", default=GoogleAdsConfig.api_version) or GoogleAdsConfig.api_version,
        customer_id=_env("GOOGLE_ADS_CUSTOMER_ID", default=GoogleAdsConfig.customer_id)
        or GoogleAdsConfig.customer_id,
        login_customer_id=_env("GOOGLE_ADS_LOGIN_CUSTOMER_ID", default=GoogleAdsConfig.login_customer_id)
        or GoogleAdsConfig.login_customer_id,
        developer_token=_env("GOOGLE_ADS_DEVELOPER_TOKEN", default="") or "",
        oauth_client_id=_env("GOOGLE_ADS_OAUTH_CLIENT_ID", default="") or "",
        oauth_client_secret=_env("GOOGLE_ADS_OAUTH_CLIENT_SECRET", default="") or "",
        oauth_refresh_token=_env("GOOGLE_ADS_OAUTH_REFRESH_TOKEN", default="") or "",
    )

    klaviyo = KlaviyoConfig(
        revision=_env("KLAVIYO_REVISION", default=KlaviyoConfig.revision) or KlaviyoConfig.revision,
        metric_id=_env("KLAVIYO_METRIC_ID", default=KlaviyoConfig.metric_id) or KlaviyoConfig.metric_id,
        by=tuple(
            cleaned
            for raw in (_env("KLAVIYO_BY", default="") or "").split(",")
            if (cleaned := raw.strip())
        ),
        private_key=_env("KLAVIYO_PRIVATE_KEY", default="") or "",
    )

    timezone = _env("REPORT_TIMEZONE", default=AppConfig.timezone) or AppConfig.timezone
    return AppConfig(
        timezone=timezone,
        sheets=sheets,
        shopify=shopify,
        meta=meta,
        google_ads=google_ads,
        klaviyo=klaviyo,
    )
