"""Copied from tender_search/services/boq_parser.py (extract_zip, find_boq_file, parse_boq, _is_direct_xlsx_zip); DB code removed."""
import csv
import os
import re
import zipfile
import fnmatch
import openpyxl
import xlrd
from pathlib import Path

from .zip_utils import _extract_all_nested


def extract_zip(zip_path: str, extract_to: str) -> list[str]:
    _extract_all_nested(Path(zip_path), Path(extract_to))
    return [str(p) for p in Path(extract_to).rglob("*") if p.is_file()]


def find_boq_file(file_paths: list[str]) -> str | None:
    for fp in file_paths:
        fname = os.path.basename(fp)
        name_no_ext = os.path.splitext(fname)[0]
        if fnmatch.fnmatch(name_no_ext.upper(), "*BOQ*"):
            return fp
    return None


def _normalize_header(val: str) -> str:
    return re.sub(r"[^a-z]", "", val.strip().lower())


def _find_columns(cells_with_col):
    desc_col = None
    qty_col = None
    unit_col = None
    for val, col in cells_with_col:
        nv = _normalize_header(val)
        if desc_col is None:
            if nv in ("description", "itemdescription", "item"):
                desc_col = col
        if qty_col is None:
            if nv in ("quantity", "qty"):
                qty_col = col
        if unit_col is None:
            if nv in ("unit", "units", "uom"):
                unit_col = col
    return desc_col, qty_col, unit_col


def _rows_to_items(rows: list) -> list[dict]:
    """rows: one list of raw cell values per sheet row (None for empty cells)."""
    header_row = None
    for r, row in enumerate(rows[:20]):
        d, q, u = _find_columns([(str(v) if v is not None else "", c) for c, v in enumerate(row)])
        if d is not None and (q is not None or u is not None):
            desc_col, qty_col, unit_col, header_row = d, q, u, r
            break

    if header_row is None:
        raise ValueError("Could not find header row with description + quantity/unit columns")

    def at(row, col):
        return row[col] if col is not None and col < len(row) else None

    items = []
    for row in rows[header_row + 1:]:
        desc_val = at(row, desc_col)
        desc = str(desc_val).strip() if desc_val is not None else ""
        if not desc or desc == "None" or _is_numeric(desc):
            continue
        qty = _to_number(at(row, qty_col))
        unit_raw = at(row, unit_col)
        items.append({
            "description": desc,
            "quantity": qty if qty is not None else "no_quantity_available",
            "unit": str(unit_raw).strip() if unit_raw is not None else "",
        })

    if not items:
        raise ValueError("No data rows found under header")
    return items


def _parse_boq_xlsx(file_path: str) -> list[dict]:
    wb = openpyxl.load_workbook(file_path, data_only=True)
    try:
        ws = wb.active
        if ws is None:
            raise ValueError("No active worksheet found")
        return _rows_to_items([list(r) for r in ws.iter_rows(values_only=True)])
    finally:
        wb.close()


def _parse_boq_xls(file_path: str) -> list[dict]:
    ws = xlrd.open_workbook(file_path).sheet_by_index(0)
    return _rows_to_items([ws.row_values(r) for r in range(ws.nrows)])


def _parse_boq_csv(file_path: str) -> list[dict]:
    # ponytail: stdlib csv only, O(n) scan, no pandas; upgrade to pandas if large/encoding issues
    with open(file_path, "r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    if not rows:
        raise ValueError("Empty CSV file")
    return _rows_to_items(rows)


def parse_boq(file_path: str) -> list[dict]:
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".xls":
        return _parse_boq_xls(file_path)
    elif ext == ".xlsx":
        return _parse_boq_xlsx(file_path)
    elif ext == ".csv":
        return _parse_boq_csv(file_path)
    else:
        raise ValueError(f"Unsupported file format: {ext} (expected .xls, .xlsx or .csv)")


def _is_direct_xlsx_zip(file_path: str) -> bool:
    # ponytail: xlsx is zip; detect via xl/workbook.xml to avoid misclassifying xlsx as container zip; upgrade to mime check if Drive strips ext
    try:
        with zipfile.ZipFile(file_path, "r") as zf:
            names = zf.namelist()
            return "xl/workbook.xml" in names or "xl/_rels/workbook.xml.rels" in names
    except zipfile.BadZipFile:
        return False


def _to_number(val):
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val) if val == val else None
    s = str(val).strip().replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def _is_numeric(val: str) -> bool:
    try:
        float(val.strip())
        return True
    except ValueError:
        return False
