from __future__ import annotations

import argparse
import json
import logging
import os
import importlib.metadata as importlib_metadata
from typing import Any, Iterable

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:  # pragma: no cover
    load_dotenv = None

if not hasattr(importlib_metadata, "packages_distributions"):
    # Compatibility for Python < 3.10 (prevents noisy prints from google-api-core)
    def _packages_distributions() -> dict[str, list[str]]:  # pragma: no cover
        return {}

    setattr(importlib_metadata, "packages_distributions", _packages_distributions)


def _iter_exception_chain(exc: BaseException) -> Iterable[BaseException]:
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        yield current
        seen.add(id(current))
        current = current.__cause__ or current.__context__


def _load_google_application_credentials_summary() -> dict[str, str]:
    path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if not path:
        return {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception:
        return {}
    out: dict[str, str] = {}
    for key in ("client_email", "project_id"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            out[key] = value.strip()
    return out


def _maybe_handle_google_sheets_http_error(exc: BaseException) -> bool:
    try:
        from googleapiclient.errors import HttpError
    except Exception:  # pragma: no cover
        return False

    http_error: HttpError | None = None
    for candidate in _iter_exception_chain(exc):
        if isinstance(candidate, HttpError):
            http_error = candidate
            break
    if http_error is None:
        return False

    content: Any = getattr(http_error, "content", None)
    if isinstance(content, bytes):
        content_text = content.decode("utf-8", errors="replace")
    else:
        content_text = str(content or "")

    try:
        payload = json.loads(content_text)
    except json.JSONDecodeError:
        payload = {}
    error = payload.get("error") if isinstance(payload, dict) else None
    if not isinstance(error, dict):
        return False

    details = error.get("details") if isinstance(error.get("details"), list) else []
    summaries = _load_google_application_credentials_summary()

    for entry in details:
        if not isinstance(entry, dict):
            continue
        if entry.get("@type") != "type.googleapis.com/google.rpc.ErrorInfo":
            continue
        reason = entry.get("reason")
        metadata = entry.get("metadata") if isinstance(entry.get("metadata"), dict) else {}
        if metadata.get("service") != "sheets.googleapis.com":
            continue

        if reason == "SERVICE_DISABLED":
            activation_url = metadata.get("activationUrl")
            consumer = metadata.get("consumer") or metadata.get("containerInfo") or "tu proyecto"
            project = summaries.get("project_id")
            suffix = f" (project_id: {project})" if project else ""
            project_flag = None
            if isinstance(consumer, str) and consumer.startswith("projects/"):
                project_flag = consumer.split("/", 1)[1]
            elif isinstance(consumer, str) and consumer:
                project_flag = consumer
            elif isinstance(project, str) and project:
                project_flag = project
            enable_hint = (
                f" Comando: `gcloud services enable sheets.googleapis.com --project {project_flag}`"
                if project_flag
                else ""
            )
            logging.error(
                "Google Sheets API está deshabilitada para %s%s. "
                "Habilítala y reintenta.%s %s",
                consumer,
                suffix,
                enable_hint,
                activation_url or "",
            )
            return True

        if reason == "ACCESS_TOKEN_SCOPE_INSUFFICIENT":
            logging.error(
                "Tus credenciales de Google no tienen scopes suficientes para Sheets. "
                "Usa un Service Account con `GOOGLE_APPLICATION_CREDENTIALS=/ruta/key.json` "
                "o re-autentica ADC con: "
                "`gcloud auth application-default login "
                "--scopes=https://www.googleapis.com/auth/cloud-platform,https://www.googleapis.com/auth/spreadsheets`."
            )
            return True

    message = error.get("message") if isinstance(error.get("message"), str) else ""
    if "The caller does not have permission" in message:
        email = summaries.get("client_email")
        hint = f" (service account: {email})" if email else ""
        logging.error(
            "La cuenta no tiene acceso al Google Sheet%s. "
            "Compartí el spreadsheet con el mail del service account y reintenta.",
            hint,
        )
        return True

    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="metrics-report")
    subparsers = parser.add_subparsers(dest="command")

    oauth_parser = subparsers.add_parser("oauth", help="OAuth helpers (local dev).")
    oauth_subparsers = oauth_parser.add_subparsers(dest="oauth_command", required=True)
    google_ads_oauth = oauth_subparsers.add_parser(
        "google-ads",
        help="Create a Google Ads OAuth refresh token from a client_secret json.",
    )
    google_ads_oauth.add_argument(
        "--client-secret",
        required=True,
        help="Path to OAuth client_secret JSON downloaded from Google Cloud Console.",
    )
    google_ads_oauth.add_argument(
        "--no-browser",
        action="store_true",
        help="Do not open the browser automatically (prints a URL instead).",
    )
    google_ads_oauth.add_argument(
        "--port",
        type=int,
        default=8080,
        help="Local callback port for OAuth redirect (default: 8080).",
    )
    google_ads_oauth.add_argument(
        "--env-file",
        default=".env",
        help="Write GOOGLE_ADS_OAUTH_REFRESH_TOKEN to this env file (default: .env).",
    )
    google_ads_oauth.add_argument(
        "--stdout",
        action="store_true",
        help="Print the refresh token to stdout (recommended for pasting into a secret manager).",
    )
    google_ads_oauth.add_argument(
        "--force",
        action="store_true",
        help="Overwrite GOOGLE_ADS_OAUTH_REFRESH_TOKEN in the env file even if already set.",
    )

    parser.add_argument(
        "--only",
        nargs="*",
        choices=["shopify", "meta", "google_ads", "klaviyo"],
        default=None,
        help="Run only a subset of tasks.",
    )
    parser.add_argument(
        "--check-sheets",
        action="store_true",
        help="Only check Google Sheets access and exit.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Do not append to Sheets.")
    args = parser.parse_args(argv)

    if load_dotenv is not None:
        load_dotenv(override=False)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.command == "oauth":
        from metrics_report.oauth import run_oauth_command

        run_oauth_command(args)
        return 0

    from metrics_report.config import load_config
    from metrics_report.pipeline import run_pipeline

    config = load_config()
    try:
        if args.check_sheets:
            from metrics_report.sheets import GoogleSheetsClient

            sheets = GoogleSheetsClient(config.sheets.spreadsheet_id)
            for sheet_name in (
                config.sheets.purchase_sheet,
                config.sheets.meta_sheet,
                config.sheets.gads_sheet,
                config.sheets.klaviyo_sheet,
            ):
                header = sheets.get_header(sheet_name)
                logging.info("Sheets OK: %s (%d columnas)", sheet_name, len(header))
            return 0

        run_pipeline(config, only=set(args.only) if args.only else None, dry_run=args.dry_run)
    except Exception as exc:
        if _maybe_handle_google_sheets_http_error(exc):
            return 2
        try:
            from google.auth.exceptions import DefaultCredentialsError, RefreshError
        except Exception:  # pragma: no cover
            DefaultCredentialsError = None  # type: ignore[assignment]
            RefreshError = None  # type: ignore[assignment]

        if DefaultCredentialsError is not None and isinstance(exc, DefaultCredentialsError):
            logging.error(
                "No se encontraron credenciales de Google (ADC). "
                "Solución: `gcloud auth application-default login` "
                "o exportar `GOOGLE_APPLICATION_CREDENTIALS=/ruta/service-account.json`."
            )
            return 2
        if RefreshError is not None and isinstance(exc, RefreshError):
            logging.error(
                "Reautenticación requerida para credenciales de Google. "
                "Ejecuta: `gcloud auth application-default login "
                "--scopes=https://www.googleapis.com/auth/cloud-platform,https://www.googleapis.com/auth/spreadsheets`."
            )
            return 2
        raise
    return 0
