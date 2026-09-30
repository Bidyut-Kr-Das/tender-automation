"""Parse a tender file given by `file_link`. No DB: each parser returns the parsed data for the webhook.

Pure parsers live in automation_v2/lib (copied from legacy without DB code).
Parsers raise on failure, which the worker turns into `file.parsed_failed`.
"""
import os
import re
import shutil
import tempfile
import zipfile
from contextlib import contextmanager
from urllib.parse import unquote

import openpyxl
from django.conf import settings

from .lib import costing_excel_parse as costing
from .lib.boq_parser import _is_direct_xlsx_zip, extract_zip, find_boq_file, parse_boq as parse_boq_rows
from .lib.downloads import _download_from_drive, _download_from_url, _extract_drive_file_id, _resolve_network_path
from .lib.gem_ra_pdf_parser import parse_ra_document
from .lib.pdf_parser import parse_gem_pdf_service


@contextmanager
def _workdir():
    # One dir per job, removed whole afterwards: covers downloads, renames and zip extracts.
    os.makedirs(settings.TENDER_PARSING_TEMP_DIR, exist_ok=True)
    d = tempfile.mkdtemp(dir=settings.TENDER_PARSING_TEMP_DIR)
    try:
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)


def _download(link: str, dest: str) -> str:
    file_id = _extract_drive_file_id(link)
    if file_id:
        _download_from_drive(file_id, dest)
    elif link.startswith(("http://", "https://")):
        _download_from_url(link, dest)
    else:
        raise ValueError(f"Unsupported file_link: {link}")
    return dest


def parse_gem_pdf(job) -> dict:
    with _workdir() as d:
        return parse_gem_pdf_service(_download(job.file_link, os.path.join(d, "document.pdf")))


def parse_ra_pdf(job) -> dict:
    with _workdir() as d:
        return parse_ra_document(_download(job.file_link, os.path.join(d, "ra.pdf")))


def parse_boq(job) -> dict:
    """Same file detection as legacy boq_parser.process_boq, minus the DB save."""
    with _workdir() as d:
        path = _download(job.file_link, os.path.join(d, "download"))
        is_zip = zipfile.is_zipfile(path)
        is_xlsx = is_zip and _is_direct_xlsx_zip(path)
        link_name = os.path.basename(unquote(job.file_link.split("?")[0]))  # S3 keys come %2F-encoded
        if link_name.lower().endswith((".xls", ".xlsx", ".csv")):
            is_zip, is_xlsx = False, link_name.lower().endswith(".xlsx")

        if is_zip and not is_xlsx:  # container zip: find the BOQ inside
            boq_path = find_boq_file(extract_zip(path, os.path.join(d, "extracted")))
            if not boq_path:
                raise FileNotFoundError("No BOQ file found among extracted files")
        else:
            if is_xlsx:
                ext = ".xlsx"
            else:
                with open(path, "rb") as f:
                    ext = ".xls" if f.read(8).startswith(b"\xD0\xCF\x11\xE0") else ".csv"  # OLE magic
            boq_path = path + ext
            os.rename(path, boq_path)
            return {"boq_file": link_name or os.path.basename(boq_path), "items": parse_boq_rows(boq_path)}
        return {"boq_file": os.path.basename(boq_path), "items": parse_boq_rows(boq_path)}


def parse_costing(job) -> dict:
    """Same table extraction as legacy costing_excel_parse.parse_costing_excel, minus DB save / laser_cost POST."""
    with _workdir() as d:
        if job.file_type == "network" and job.decrypted_fileId:
            src = _resolve_network_path(job.decrypted_fileId)
        elif job.file_link and re.match(r"^https?://", job.file_link.strip(), re.I):
            src = os.path.join(d, "costing.xlsx")
            if costing._is_drive_link(job.file_link):
                file_id = costing._extract_drive_file_id(job.file_link)
                if not file_id:
                    raise ValueError(f"Could not extract Drive file ID from link: {job.file_link}")
                costing._download_drive_file(file_id, src)  # service-account download, as legacy
            else:
                _download_from_url(job.file_link, src)
        elif job.file_link:
            src = job.file_link
        else:
            raise ValueError("file_link or decrypted_fileId is required")
        if not os.path.exists(src):
            raise FileNotFoundError(f"Costing file not found at path: {src}")

        wb = openpyxl.load_workbook(src, data_only=True)
        sheets = [ws for ws in wb.worksheets if "AUTO CALCULATION SHEET" in ws.title.upper()]
        if not sheets:
            raise ValueError("AUTO CALCULATION SHEET tab not found")
        tables = []
        for ws in sheets:
            rows = costing._find_all_header_rows(ws)
            for i, hr in enumerate(rows):
                end = rows[i + 1] if i + 1 < len(rows) else ws.max_row + 1
                if table := costing._parse_table(ws, hr, end):
                    tables.append(table)
        if not tables:
            raise ValueError("No valid table headers found (DOCKET NO + PROPOSE ERP)")
        return {
            "tables": tables,
            "price": costing._find_price_basis(sheets[0]),
            "applicableIndex": costing._find_applicable_index(sheets[0]),
        }


PARSERS = {
    "GEM_PDF_PARSING": parse_gem_pdf,
    "RA_GEM_PDF_PARSING": parse_ra_pdf,
    "NON_GEM_BOQ_PARSING": parse_boq,
    "COSTING_ATTACHMENT_PARSING": parse_costing,
}
