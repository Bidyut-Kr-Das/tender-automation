"""Copied from tender_search/services/boq_parser.py (extract_zip, find_boq_file, parse_boq, _is_direct_xlsx_zip); DB code removed."""
import csv
import os
import re
import zipfile
import fnmatch
import openpyxl
import xlrd


def extract_zip(zip_path: str, extract_to: str) -> list[str]:
    extracted_files = []

    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(extract_to)

    for root, _dirs, files in os.walk(extract_to):
        for fname in files:
            fpath = os.path.join(root, fname)
            extracted_files.append(fpath)

            if fname.lower().endswith(".zip"):
                nested_dir = os.path.join(extract_to, fname.replace(".zip", "_extracted"))
                os.makedirs(nested_dir, exist_ok=True)
                nested_files = extract_zip(fpath, nested_dir)
                extracted_files.extend(nested_files)

    return extracted_files


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


def _parse_boq_xlsx(file_path: str) -> list[dict]:
    wb = openpyxl.load_workbook(file_path, data_only=True)
    ws = wb.active
    if ws is None:
        raise ValueError("No active worksheet found")

    header_row = None
    desc_col = qty_col = unit_col = None

    for row in ws.iter_rows(min_row=1, max_row=20, values_only=False):
        cells = [(str(c.value) if c.value is not None else "", c.column) for c in row]
        d, q, u = _find_columns(cells)
        if d is not None and (q is not None or u is not None):
            desc_col = d
            qty_col = q
            unit_col = u
            header_row = row[0].row
            break

    if header_row is None or desc_col is None:
        wb.close()
        raise ValueError("Could not find header row with description + quantity/unit columns")

    items = []
    for row in ws.iter_rows(min_row=header_row + 1, values_only=False):
        desc_val = row[desc_col - 1].value if desc_col <= len(row) else None
        desc = str(desc_val).strip() if desc_val is not None else ""
        if not desc or desc == "None" or _is_numeric(desc):
            continue

        qty_raw = row[qty_col - 1].value if qty_col and qty_col <= len(row) else None
        unit_raw = row[unit_col - 1].value if unit_col and unit_col <= len(row) else None

        qty = _to_number(qty_raw)
        items.append({
            "description": desc,
            "quantity": qty if qty is not None else "no_quantity_available",
            "unit": str(unit_raw).strip() if unit_raw is not None else "",
        })

    wb.close()

    if not items:
        raise ValueError("No data rows found under header")

    return items


def _parse_boq_xls(file_path: str) -> list[dict]:
    wb = xlrd.open_workbook(file_path)
    ws = wb.sheet_by_index(0)

    header_row = None
    desc_col = qty_col = unit_col = None

    for r in range(min(20, ws.nrows)):
        cells = [(str(ws.cell_value(r, c)), c) for c in range(ws.ncols)]
        d, q, u = _find_columns(cells)
        if d is not None and (q is not None or u is not None):
            desc_col = d
            qty_col = q
            unit_col = u
            header_row = r
            break

    if header_row is None or desc_col is None:
        raise ValueError("Could not find header row with description + quantity/unit columns")

    items = []
    for r in range(header_row + 1, ws.nrows):
        desc = str(ws.cell_value(r, desc_col)).strip()
        if not desc or desc == "None" or _is_numeric(desc):
            continue

        qty_raw = ws.cell_value(r, qty_col) if qty_col is not None else None
        unit_raw = ws.cell_value(r, unit_col) if unit_col is not None else None

        qty = _to_number(qty_raw)
        items.append({
            "description": desc,
            "quantity": qty if qty is not None else "no_quantity_available",
            "unit": str(unit_raw).strip() if unit_raw is not None else "",
        })

    if not items:
        raise ValueError("No data rows found under header")

    return items


def _parse_boq_csv(file_path: str) -> list[dict]:
    # ponytail: stdlib csv only, O(n) scan, no pandas; upgrade to pandas if large/encoding issues
    with open(file_path, "r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))

    if not rows:
        raise ValueError("Empty CSV file")

    header_row = None
    desc_col = qty_col = unit_col = None
    for r in range(min(20, len(rows))):
        cells = [(str(rows[r][c]) if c < len(rows[r]) else "", c) for c in range(len(rows[r]))]
        d, q, u = _find_columns(cells)
        if d is not None and (q is not None or u is not None):
            desc_col, qty_col, unit_col, header_row = d, q, u, r
            break

    if header_row is None or desc_col is None:
        raise ValueError("Could not find header row with description + quantity/unit columns")

    items = []
    for r in range(header_row + 1, len(rows)):
        row = rows[r]
        desc = str(row[desc_col]).strip() if desc_col < len(row) else ""
        if not desc or desc == "None" or _is_numeric(desc):
            continue
        qty_raw = row[qty_col].strip() if qty_col is not None and qty_col < len(row) else None
        unit_raw = row[unit_col].strip() if unit_col is not None and unit_col < len(row) else None
        qty = _to_number(qty_raw)
        # ponytail: empty qty -> sentinel string, keeps downstream format stable; change to None if callers handle null
        items.append({
            "description": desc,
            "quantity": qty if qty is not None else "no_quantity_available",
            "unit": str(unit_raw).strip() if unit_raw is not None else "",
        })

    if not items:
        raise ValueError("No data rows found under header")
    return items


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
