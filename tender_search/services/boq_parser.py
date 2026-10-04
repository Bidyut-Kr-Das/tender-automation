import csv
import os
import re
import json
import shutil
import zipfile
import logging
import tempfile
import fnmatch

import openpyxl
import xlrd
from django.conf import settings
from tender_search.models import TenderMerged
from pathlib import Path

from .downloads import download_from_drive, download_from_url, extract_drive_file_id
from .zip_utils import _extract_all_nested

logger = logging.getLogger(__name__)

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


_HEADER_KEYWORDS = {
    "description": ["description", "item", "particulars", "work", "nameofwork", "name of work", "material", "specification"],
    "quantity": ["qty", "quantity", "totalqty", "total qty", "estimated  rate"],
    "unit": ["unit", "uom", "measure"],
}


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


def _parse_boq_zip(zip_path: str, extract_to: str) -> tuple[str, list[dict]]:
    extracted_files = extract_zip(zip_path, extract_to)
    boq_path = find_boq_file(extracted_files)
    if not boq_path:
        raise FileNotFoundError("No BOQ file found among extracted files")
    items = parse_boq(boq_path)
    return boq_path, items


def _parse_boq_direct(file_path: str) -> list[dict]:
    return parse_boq(file_path)


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


def _save_boq_core(reference_no: str, items: list[str]) -> dict:
    tender = TenderMerged.objects.filter(referenceno=reference_no).first()
    if not tender:
        return {"success": False, "error": f"TenderMerged not found for reference_no={reference_no}"}
    tender.size = json.dumps(items)
    tender.parsestatus = "COMPLETED"
    tender.parseerror = None
    tender.save()
    logger.info("Saved BOQ items for %s (size field)", reference_no)
    print(json.dumps(items))
    return {"success": True}


def save_boq_from_zip(reference_no: str, items: list[str]) -> dict:
    logger.info("Saving BOQ from ZIP for %s", reference_no)
    return _save_boq_core(reference_no, items)


def save_boq_from_direct(reference_no: str, items: list[str]) -> dict:
    logger.info("Saving BOQ from direct file for %s", reference_no)
    return _save_boq_core(reference_no, items)


def _save_failure_to_db(reference_no: str, error_msg: str):
    try:
        tender = TenderMerged.objects.filter(referenceno=reference_no).first()
        if tender:
            tender.parsestatus = "FAILED"
            tender.parseerror = error_msg
            tender.save()
            logger.info("Updated parsestatus=FAILED for %s", reference_no)
    except Exception as e:
        logger.warning("Could not save failure to DB for %s: %s", reference_no, e)


def process_boq(reference_no: str, file_link: str | None = None, drive_link: str | None = None) -> dict:
    # ponytail: file_link is S3, drive_link legacy alias — use whichever provided
    link = file_link or drive_link or ""
    result = {
        "reference_no": reference_no,
        "success": False,
        "boq_file": None,
        "items": [],
        "error": None,
    }

    file_id = extract_drive_file_id(link)
    is_drive = file_id is not None
    is_http = link.startswith("http://") or link.startswith("https://")
    if not is_drive and not is_http:
        result["error"] = f"Unsupported link: {link}"
        return result

    temp_dir = getattr(settings, "TENDER_PARSING_TEMP_DIR", tempfile.gettempdir())
    safe_name = reference_no.replace("/", "-").replace("\\", "-")
    download_path = os.path.join(temp_dir, f"{safe_name}_download")
    zip_path = download_path
    extract_dir = os.path.join(temp_dir, f"{safe_name}_extracted")
    direct_path = None

    try:
        if is_drive:
            logger.info("Downloading Drive file_id=%s -> %s", file_id, download_path)
            download_from_drive(file_id, download_path)
        else:
            logger.info("Downloading URL %s -> %s", link, download_path)
            download_from_url(link, download_path)

        is_zip = zipfile.is_zipfile(download_path)
        is_xlsx_direct = _is_direct_xlsx_zip(download_path) if is_zip else False
        # ponytail: S3 per-file already extracted via zip_utils — skip zip if link is direct excel/csv
        link_lower = link.lower().split("?")[0]
        # handle %2F encoded keys — check after decoding
        try:
            from urllib.parse import unquote
            link_lower = unquote(link_lower)
        except Exception:
            pass
        if link_lower.endswith((".xls", ".xlsx", ".csv")):
            logger.info("Link %s indicates direct file, skipping zip extract", link)
            is_zip = False
            is_xlsx_direct = link_lower.endswith(".xlsx")

        if is_zip and not is_xlsx_direct:
            # ponytail: container zip -> extract + find BOQ; ceiling: assumes container not xlsx; upgrade to Content-Disposition check if Drive mangles name
            logger.info("Detected container ZIP, extracting %s -> %s", download_path, extract_dir)
            os.makedirs(extract_dir, exist_ok=True)
            boq_path, items = _parse_boq_zip(download_path, extract_dir)
            result["boq_file"] = os.path.basename(boq_path)
            logger.info("Found BOQ file: %s", boq_path)
            result["items"] = [
                f"{i}. {item['description']}_{item['quantity']}_{item['unit']}"
                for i, item in enumerate(items, start=1)
            ]
            result["success"] = True
            result["db_save"] = save_boq_from_zip(reference_no, result["items"])
        else:
            # direct file: xlsx/xls/csv — no recursive search
            if is_xlsx_direct:
                ext = ".xlsx"
            else:
                # ponytail: detect xls via OLE magic, else csv; ceiling: no mime lib, fails on misnamed binary; add python-magic if needed
                with open(download_path, "rb") as f:
                    header = f.read(8)
                if header.startswith(b"\xD0\xCF\x11\xE0"):
                    ext = ".xls"
                elif not is_zip:
                    # try csv sniff: if not zip and not OLE, assume csv (or xlsx already handled)
                    ext = ".csv"
                    # validate csv quickly: if file has no comma and no header match, parse will raise
                else:
                    ext = ".xlsx"
            direct_path = download_path + ext
            if download_path != direct_path:
                if os.path.exists(direct_path):
                    os.remove(direct_path)
                os.rename(download_path, direct_path)
                zip_path = direct_path  # for cleanup tracking
            else:
                direct_path = download_path
            logger.info("Detected direct file %s, parsing without extraction", direct_path)
            items = _parse_boq_direct(direct_path)
            result["boq_file"] = os.path.basename(direct_path)
            result["items"] = [
                f"{i}. {item['description']}_{item['quantity']}_{item['unit']}"
                for i, item in enumerate(items, start=1)
            ]
            result["success"] = True
            result["db_save"] = save_boq_from_direct(reference_no, result["items"])

    except FileNotFoundError as e:
        logger.exception("BOQ file not found")
        result["error"] = str(e)
        _save_failure_to_db(reference_no, str(e))
    except Exception as e:
        logger.exception("BOQ processing failed")
        result["error"] = str(e)
        _save_failure_to_db(reference_no, str(e))

    finally:
        for p in [zip_path, direct_path]:
            if p and os.path.exists(p) and os.path.isfile(p):
                try:
                    os.remove(p)
                except Exception as e:
                    logger.warning("Could not delete %s: %s", p, e)
        if os.path.exists(extract_dir):
            try:
                shutil.rmtree(extract_dir, ignore_errors=True)
            except Exception as e:
                logger.warning("Could not delete %s: %s", extract_dir, e)

    return result
