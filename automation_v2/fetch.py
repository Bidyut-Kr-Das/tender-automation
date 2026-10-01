"""Download tender files and upload them to S3. No DB: each fetcher returns the files for the webhook.

Scraping helpers live in automation_v2/lib (copied from legacy without DB code);
the legacy DB-writing wrappers (download_gem_pdf, download_ra_pdf, TenderFiles inserts) are not carried over.
"""
import asyncio
import logging
import os
from pathlib import Path

from django.conf import settings
from playwright.sync_api import sync_playwright

from .lib import gem_pdf_downloader as gem, gem_ra_pdf_downloader as ra
from .lib.file_storage import file_storage
from .lib.gem_bid_results import find_gem_id_result
from .lib.non_gem_tender_pdf_downloader import login_tender247
from .lib.tender_tiger import login_tiger

logger = logging.getLogger(__name__)

TENDER_DOCUMENT, BOQ_FILE = "tenderDocument", "BOQ_FILE"  # tag values from legacy tender_search/constants.py

if hasattr(asyncio, "WindowsProactorEventLoopPolicy"):  # same as the legacy worker, for tender247 on Windows
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())


class FetchFailed(Exception):
    pass


def _file(s3: dict, tag: str, source: str) -> dict:
    name = s3["key"].split("/")[-1]
    return {"name": name, "extension": Path(name).suffix, "url": s3["url"], "key": s3["key"], "tag": tag, "source": source}


def _search_and_download(ref: str, mod, download, want_status: bool = False) -> tuple[str | None, str | None]:
    """Legacy search order: ongoing bids first, then with bid/ra status. Returns (pdf_path, bid_status)."""
    status = None
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            executable_path=os.environ.get("CHROME_PATH") or mod.detect_chrome_path(),
            headless=settings.HEADLESS_BROWSER,
            args=["--disable-blink-features=AutomationControlled", "--disable-features=ChromeWhatsNewUI"],
        )
        try:
            page = browser.new_page()
            for bid_ra in (False, True):
                mod.perform_search(page, ref, check_bid_ra_status=bid_ra)
                if not mod.wait_for_search_results(page, ref):
                    continue
                if want_status:
                    try:
                        mod.delay(2000)
                        status = (find_gem_id_result(page, ref) or {}).get("bidStatus") or status
                    except Exception as e:  # status is a bonus; never fail the download for it
                        logger.warning("%s: bid status extraction failed: %s", ref, e)
                result = download(page, ref, settings.TENDER_PARSING_TEMP_DIR)
                if result["success"]:
                    return result["pdfPath"], status
                logger.info("%s: download failed (bid_ra=%s): %s", ref, bid_ra, result.get("error"))
        finally:
            browser.close()
    return None, status


def _upload_pdf(path: str, ref: str, tag: str) -> dict:
    try:
        return _file(file_storage.upload(path, reference_no=ref), tag, "gem")
    finally:
        os.remove(path)


def fetch_gem(job) -> dict:
    path, _ = _search_and_download(job.referenceNo, gem, gem.try_download)
    if not path:
        raise FetchFailed("Could not download GeM PDF")
    return {"files": [_upload_pdf(path, job.referenceNo, TENDER_DOCUMENT)], "bidStatus": None}


def fetch_ra(job) -> dict:
    path, status = _search_and_download(job.referenceNo, ra, ra.try_download_ra, want_status=True)
    if not path:
        raise FetchFailed(f"Could not download RA PDF (bidStatus={status!r})")
    return {"files": [_upload_pdf(path, job.referenceNo, "raDocument")], "bidStatus": status}


def _non_gem_tag(name: str) -> str:
    is_boq_excel = "boq" in name.lower() and Path(name).suffix.lower() in (".xls", ".xlsx", ".xlsm", ".xlsb")
    return BOQ_FILE if is_boq_excel else TENDER_DOCUMENT


def fetch_non_gem(job) -> dict:
    ref = job.referenceNo
    folder = settings.GOOGLE_DRIVE_FOLDER_ID or None
    if not settings.TENDER247_EMAIL or not settings.TENDER247_PASSWORD:
        raise ValueError("TENDER247_EMAIL and TENDER247_PASSWORD must be configured")

    asyncio.set_event_loop(asyncio.new_event_loop())
    result, source = login_tender247(settings.TENDER247_EMAIL, settings.TENDER247_PASSWORD, ref, folder), "tender247"
    if not result.get("success"):
        logger.info("%s: tender247 failed (%s), trying tiger", ref, result.get("error"))
        result, source = login_tiger(settings.TENDER_TIGER_EMAIL, settings.TENDER_TIGER_PASSWORD, ref, folder), "tendertiger"
    if not result.get("success"):
        raise FetchFailed(f"tender247 and tendertiger both failed: {result.get('error') or 'no result'}")

    s3_list = result.get("s3_list") or ([result["s3"]] if result.get("s3") else [])
    files = [_file(s3, _non_gem_tag(s3["key"]), source) for s3 in s3_list if s3 and s3.get("url")]
    if not files:
        raise FetchFailed(f"{source} returned no files")
    return {"files": files, "bidStatus": None}


FETCHERS = {"GEM_DOWNLOAD": fetch_gem, "RA_GEM_DOWNLOAD": fetch_ra, "NON_GEM_DOWNLOAD": fetch_non_gem}
