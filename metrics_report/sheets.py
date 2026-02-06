from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import google.auth
from googleapiclient.discovery import build


_LOG = logging.getLogger(__name__)
_YMD_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DMY_RE = re.compile(r"^(?P<d>\d{1,2})[/-](?P<m>\d{1,2})[/-](?P<y>\d{4})$")


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


def _sheets_serial_to_date(value: float) -> date | None:
    # Google Sheets "date" serials are days since 1899-12-30.
    # See: https://support.google.com/docs/answer/3092969
    try:
        if value != value:  # NaN
            return None
        days = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if days <= 0:
        return None
    epoch = date(1899, 12, 30)
    try:
        return epoch + timedelta(days=days)
    except (OverflowError, ValueError):
        return None


def _coerce_cell_to_ymd(value: Any) -> str | None:
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        if _YMD_RE.match(s):
            return s
        # Common for Sheets locales: "21/12/2025" (dd/mm/yyyy) or "21-12-2025".
        m = _DMY_RE.match(s)
        if m:
            try:
                d = date(int(m.group("y")), int(m.group("m")), int(m.group("d")))
                return d.isoformat()
            except ValueError:
                return None
        # Sometimes the API returns full datetimes; keep the date part if it looks ISO-ish.
        if len(s) >= 10 and _YMD_RE.match(s[:10]):
            return s[:10]
        return None

    if isinstance(value, (int, float)):
        d = _sheets_serial_to_date(float(value))
        return d.isoformat() if d else None

    return None


def _coerce_cell_to_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None

    if isinstance(value, (int, float)):
        try:
            f = float(value)
        except (TypeError, ValueError, OverflowError):
            return None
        if f != f or f in (float("inf"), float("-inf")):
            return None
        return f

    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        s = s.replace(",", ".")
        try:
            f = float(s)
        except (TypeError, ValueError):
            return None
        if f != f or f in (float("inf"), float("-inf")):
            return None
        return f

    return None


@dataclass(frozen=True)
class MaxDateResult:
    header: list[str]
    date_column: str
    max_date: str | None


class GoogleSheetsClient:
    def __init__(self, spreadsheet_id: str):
        _maybe_load_local_credentials()
        creds, project_id = google.auth.default(scopes=["https://www.googleapis.com/auth/spreadsheets"])
        quota_project_id = (
            os.getenv("GOOGLE_CLOUD_QUOTA_PROJECT")
            or os.getenv("GOOGLE_CLOUD_PROJECT")
            or (project_id.strip() if isinstance(project_id, str) else "")
        )
        if quota_project_id and hasattr(creds, "with_quota_project"):
            creds = creds.with_quota_project(quota_project_id)
        self._service = build("sheets", "v4", credentials=creds, cache_discovery=False)
        self._spreadsheet_id = spreadsheet_id

    def get_values(
        self,
        sheet_name: str,
        a1_range: str,
        *,
        value_render_option: str | None = None,
        date_time_render_option: str | None = None,
    ) -> list[list[Any]]:
        sheet = _quote_sheet(sheet_name)
        kwargs: dict[str, Any] = {}
        if value_render_option is not None:
            kwargs["valueRenderOption"] = value_render_option
        if date_time_render_option is not None:
            kwargs["dateTimeRenderOption"] = date_time_render_option
        resp = (
            self._service.spreadsheets()
            .values()
            .get(
                spreadsheetId=self._spreadsheet_id,
                range=f"{sheet}!{a1_range}",
                **kwargs,
            )
            .execute()
        )
        values = resp.get("values") or []
        return list(values)

    def update_values(
        self,
        sheet_name: str,
        a1_range: str,
        *,
        values: list[list[Any]],
        value_input_option: str = "USER_ENTERED",
    ) -> None:
        sheet = _quote_sheet(sheet_name)
        (
            self._service.spreadsheets()
            .values()
            .update(
                spreadsheetId=self._spreadsheet_id,
                range=f"{sheet}!{a1_range}",
                valueInputOption=value_input_option,
                body={"values": values},
            )
            .execute()
        )

    def batch_update_values(
        self,
        sheet_name: str,
        *,
        updates: list[tuple[str, list[list[Any]]]],
        value_input_option: str = "USER_ENTERED",
    ) -> None:
        if not updates:
            return
        sheet = _quote_sheet(sheet_name)
        data = [{"range": f"{sheet}!{a1_range}", "values": values} for a1_range, values in updates]
        (
            self._service.spreadsheets()
            .values()
            .batchUpdate(
                spreadsheetId=self._spreadsheet_id,
                body={
                    "valueInputOption": value_input_option,
                    "data": data,
                },
            )
            .execute()
        )

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
        dates: list[str] = []
        for cell in raw_values:
            ymd = _coerce_cell_to_ymd(cell)
            if ymd:
                dates.append(ymd)
        max_date = max(dates) if dates else None
        return MaxDateResult(header=header, date_column=date_column, max_date=max_date)

    def consolidate_sum_by_date(
        self,
        sheet_name: str,
        *,
        date_headers: list[str],
        sum_headers: list[str],
    ) -> int:
        header = self.get_header(sheet_name)
        if not header:
            raise ValueError(f"Sheet '{sheet_name}' has no header row")

        date_col_idx = next((i for i, h in enumerate(header) if h in date_headers), None)
        if date_col_idx is None:
            raise ValueError(f"Sheet '{sheet_name}' missing date header (expected one of: {date_headers})")

        sum_col_indices: list[int] = []
        for name in sum_headers:
            idx = next((i for i, h in enumerate(header) if h == name), None)
            if idx is None:
                raise ValueError(f"Sheet '{sheet_name}' missing column '{name}'")
            sum_col_indices.append(idx)

        date_letter = _col_letter(date_col_idx)
        sum_letters = [_col_letter(idx) for idx in sum_col_indices]

        date_values = self.get_values(sheet_name, f"{date_letter}2:{date_letter}")
        sum_values = [self.get_values(sheet_name, f"{letter}2:{letter}") for letter in sum_letters]
        data_rows = max([len(date_values)] + [len(col) for col in sum_values])
        if data_rows <= 0:
            return 0

        occurrences: dict[str, int] = {}
        totals: dict[str, list[float]] = {}
        for row_idx in range(data_rows):
            date_cell = date_values[row_idx][0] if row_idx < len(date_values) and date_values[row_idx] else None
            ymd = _coerce_cell_to_ymd(date_cell)
            if not ymd:
                continue

            occurrences[ymd] = occurrences.get(ymd, 0) + 1
            acc = totals.get(ymd)
            if acc is None:
                acc = [0.0] * len(sum_headers)
                totals[ymd] = acc

            for col_idx, col in enumerate(sum_values):
                cell = col[row_idx][0] if row_idx < len(col) and col[row_idx] else None
                number = _coerce_cell_to_number(cell)
                if number is not None:
                    acc[col_idx] += number

        duplicates_removed = sum(count - 1 for count in occurrences.values() if count > 1)
        if duplicates_removed <= 0:
            return 0

        def fmt(value: float) -> int | float:
            if abs(value - round(value)) < 1e-9:
                return int(round(value))
            return value

        sorted_dates = sorted(totals.keys())
        rows_to_write = min(len(sorted_dates), data_rows)
        padding = max(data_rows - rows_to_write, 0)

        updates: list[tuple[str, list[list[Any]]]] = []
        updates.append(
            (
                f"{date_letter}2:{date_letter}{data_rows + 1}",
                [[d] for d in sorted_dates[:rows_to_write]] + [[""]] * padding,
            )
        )
        for idx, letter in enumerate(sum_letters):
            updates.append(
                (
                    f"{letter}2:{letter}{data_rows + 1}",
                    [[fmt(totals[d][idx])] for d in sorted_dates[:rows_to_write]] + [[""]] * padding,
                )
            )

        self.batch_update_values(sheet_name, updates=updates)
        return duplicates_removed

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
