from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import google.auth
from googleapiclient.discovery import build


_LOG = logging.getLogger(__name__)
_YMD_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _adc_credentials_path() -> Path | None:
    configured = os.getenv("CLOUDSDK_CONFIG")
    if configured:
        return Path(configured) / "application_default_credentials.json"

    appdata = os.getenv("APPDATA")
    if appdata:
        return Path(appdata) / "gcloud" / "application_default_credentials.json"

    return Path.home() / ".config" / "gcloud" / "application_default_credentials.json"


def _maybe_load_local_credentials() -> None:
    value = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if value is not None:
        if value.strip():
            return
        os.environ.pop("GOOGLE_APPLICATION_CREDENTIALS", None)

    adc = _adc_credentials_path()
    if adc is not None and adc.is_file():
        return

    candidates = [
        Path.cwd() / "gs_cred.json",
        Path(__file__).resolve().parents[1] / "gs_cred.json",
    ]
    for candidate in candidates:
        if candidate.is_file():
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(candidate)
            _LOG.info("Using Google credentials from %s", candidate)
            return


def _quote_sheet(sheet_name: str) -> str:
    if re.search(r"[\\s'!]", sheet_name):
        return "'" + sheet_name.replace("'", "''") + "'"
    return sheet_name


def _col_letter(col_index: int) -> str:
    if col_index < 0:
        raise ValueError("col_index must be >= 0")
    out = ""
    n = col_index + 1
    while n:
        n, rem = divmod(n - 1, 26)
        out = chr(ord("A") + rem) + out
    return out


@dataclass(frozen=True)
class MaxDateResult:
    header: list[str]
    date_column: str
    max_date: str | None


class GoogleSheetsClient:
    def __init__(self, spreadsheet_id: str):
        _maybe_load_local_credentials()
        creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/spreadsheets"])
        self._service = build("sheets", "v4", credentials=creds, cache_discovery=False)
        self._spreadsheet_id = spreadsheet_id

    def get_header(self, sheet_name: str) -> list[str]:
        sheet = _quote_sheet(sheet_name)
        resp = (
            self._service.spreadsheets()
            .values()
            .get(spreadsheetId=self._spreadsheet_id, range=f"{sheet}!1:1")
            .execute()
        )
        values = resp.get("values") or []
        return list(values[0]) if values else []

    def get_max_ymd_in_column(self, sheet_name: str, *, date_headers: list[str]) -> MaxDateResult:
        header = self.get_header(sheet_name)
        if not header:
            raise ValueError(f"Sheet '{sheet_name}' has no header row")

        date_col_idx = next((i for i, h in enumerate(header) if h in date_headers), None)
        if date_col_idx is None:
            raise ValueError(f"Sheet '{sheet_name}' missing date header (expected one of: {date_headers})")

        date_column = header[date_col_idx]
        letter = _col_letter(date_col_idx)
        sheet = _quote_sheet(sheet_name)
        resp = (
            self._service.spreadsheets()
            .values()
            .get(spreadsheetId=self._spreadsheet_id, range=f"{sheet}!{letter}2:{letter}")
            .execute()
        )
        raw_values = [row[0] for row in (resp.get("values") or []) if row]
        dates = [v for v in raw_values if isinstance(v, str) and _YMD_RE.match(v)]
        max_date = max(dates) if dates else None
        return MaxDateResult(header=header, date_column=date_column, max_date=max_date)

    def append_rows(self, sheet_name: str, *, header: list[str], rows: list[dict[str, Any]]) -> None:
        if not rows:
            _LOG.info("No rows to append to sheet '%s'", sheet_name)
            return

        col_index = {name: i for i, name in enumerate(header)}
        values: list[list[Any]] = []
        for row in rows:
            out: list[Any] = [""] * len(header)
            for key, value in row.items():
                idx = col_index.get(key)
                if idx is None:
                    raise ValueError(f"Sheet '{sheet_name}' missing column '{key}'")
                out[idx] = value
            values.append(out)

        sheet = _quote_sheet(sheet_name)
        (
            self._service.spreadsheets()
            .values()
            .append(
                spreadsheetId=self._spreadsheet_id,
                range=f"{sheet}!A1",
                valueInputOption="USER_ENTERED",
                insertDataOption="INSERT_ROWS",
                body={"values": values},
            )
            .execute()
        )
