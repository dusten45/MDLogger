"""현재 기록 전체를 CSV / XLSX 로 내보낸다. 컬럼은 DB 스키마와 동일."""

from __future__ import annotations

import csv
from collections.abc import Sequence
from pathlib import Path

from .db import COLUMNS

_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r", "\n")


def _spreadsheet_safe(value):
    """스프레드시트가 사용자 문자열을 수식으로 해석하지 못하게 한다."""
    if isinstance(value, str) and value.startswith(_FORMULA_PREFIXES):
        return f"'{value}"
    return value


def _row_values(row) -> list:
    """sqlite3.Row 또는 dict 에서 안전한 값을 스키마 컬럼 순서대로 추출."""
    return [_spreadsheet_safe(row[c]) for c in COLUMNS]


def export_csv(path: str | Path, rows: Sequence) -> None:
    # utf-8-sig: Excel 에서 한글이 깨지지 않도록 BOM 포함
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(COLUMNS)
        for row in rows:
            writer.writerow(_row_values(row))


def export_xlsx(path: str | Path, rows: Sequence) -> None:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "games"
    ws.append(COLUMNS)
    for row in rows:
        ws.append(_row_values(row))
    wb.save(str(path))
