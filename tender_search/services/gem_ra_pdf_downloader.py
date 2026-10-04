import os
import re
import time
from urllib.parse import urljoin
from playwright.sync_api import sync_playwright
from .file_storage import file_storage
from .gem_pdf_parser_ai import save_extraction_to_db
from .gem_bid_results import find_gem_id_result
from django.conf import settings

from .browser import delay, detect_chrome_path
from .gem_pdf_downloader import perform_search, wait_for_search_results as _wait_for_search_results


def wait_for_search_results(page, gem_id: str, timeout: int = 15000) -> bool:
    return _wait_for_search_results(page, gem_id, timeout, selector="div.block_header")


def _find_ra_link(page, gem_id: str):
    ra_selector = (
        'a.bid_no_hover[href*="showradocumentPdf"], '
        'a.bid_no_hover[href*="list-ra-schedules"]'
    )

    direct = page.locator(ra_selector).filter(has_text=gem_id).first
    if direct.count() > 0:
        return direct, direct.get_attribute("href")

    row = page.locator("div.block_header").filter(has_text=gem_id).first
    if row.count() == 0:
        return None, None

    ra_link = row.locator(ra_selector).first
    if ra_link.count() == 0:
        return None, None

    return ra_link, ra_link.get_attribute("href")


def _new_pdf_path(download_dir: str, gem_id: str) -> str:
    safe_name = gem_id.replace("/", "-")
    os.makedirs(download_dir, exist_ok=True)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    return os.path.join(download_dir, f"{safe_name}_{timestamp}.pdf")


def try_download_ra_direct(page, href: str, save_path: str) -> dict:
    full_url = urljoin("https://bidplus.gem.gov.in", href)
    print(f"  trying direct RA download from {full_url}")
    response = page.request.get(full_url)
    if not response.ok:
        return {"success": False, "error": f"HTTP {response.status}"}

    body = response.body()
    if len(body) < 100 or not body.startswith(b"%PDF"):
        return {
            "success": False,
            "error": "Response is not a PDF (likely redirected to schedules page)",
        }

    with open(save_path, "wb") as f:
        f.write(body)
    print(f"  direct RA PDF saved -> {save_path} ({len(body)} bytes)")
    return {"success": True, "pdfPath": save_path}


def _extract_first_ra_doc_url(html: str):
    for match in re.finditer(
        r'<a\b[^>]*href=["\']([^"\']*showradocumentPdf[^"\']*)["\'][^>]*>(.*?)</a>',
        html,
        re.IGNORECASE | re.DOTALL,
    ):
        text = re.sub(r"<[^>]+>", " ", match.group(2))
        if "RA" in text.upper() or "DOCUMENT" in text.upper():
            return urljoin("https://bidplus.gem.gov.in", match.group(1))

    match = re.search(
        r'href=["\']([^"\']*showradocumentPdf[^"\']*)["\']',
        html,
        re.IGNORECASE,
    )
    if match:
        return urljoin("https://bidplus.gem.gov.in", match.group(1))
    return None


def try_download_ra_from_schedules_html(page, schedules_url: str, save_path: str) -> dict:
    print(f"  fetching schedules HTML from {schedules_url}")
    response = page.request.get(schedules_url)
    if not response.ok:
        return {"success": False, "error": f"HTTP {response.status} on schedules page"}

    doc_url = _extract_first_ra_doc_url(response.text())
    if not doc_url:
        return {"success": False, "error": "No RA Document link found in schedules HTML"}

    print(f"  found first RA Document URL: {doc_url}")
    return try_download_ra_direct(page, doc_url, save_path)


def _click_ra_document(new_page, save_path: str) -> dict:
    delay(2000)
    ra_doc_btn = new_page.locator("text=RA DOCUMENT").first
    if ra_doc_btn.count() == 0:
        ra_doc_btn = new_page.locator("a, button").filter(has_text="RA DOCUMENT").first
    if ra_doc_btn.count() == 0:
        return {"success": False, "error": "RA DOCUMENT button not found on schedules page"}

    print("  clicking first RA DOCUMENT button...")
    with new_page.expect_download(timeout=60000) as download_info:
        ra_doc_btn.click()
    download = download_info.value
    download.save_as(save_path)
    print(f"  RA PDF saved from schedules page -> {save_path}")
    return {"success": True, "pdfPath": save_path}


def try_download_ra_via_click(page, link, gem_id: str, save_path: str) -> dict:
    print("  clicking RA link...")
    download = None
    new_page = None
    try:
        with page.context.expect_page(timeout=20000) as page_info:
            with page.expect_download(timeout=8000) as download_info:
                link.click()
            try:
                download = download_info.value
            except Exception:
                download = None
    except Exception as e:
        print(f"  no page opened after click: {e}")
        return {"success": False, "error": "No download or page opened on RA link click"}

    if download is not None:
        print("  RA PDF downloaded directly on click")
        download.save_as(save_path)
        print(f"  RA PDF saved -> {save_path}")
        return {"success": True, "pdfPath": save_path}

    try:
        new_page = page_info.value
    except Exception:
        new_page = None

    if new_page is not None:
        try:
            new_page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
        delay(2000)
        current_url = new_page.url
        print(f"  opened page URL: {current_url}")

        if "list-ra-schedules" in current_url:
            print("  detected RA schedules page, parsing HTML for first RA Document...")
            html = new_page.content()
            doc_url = _extract_first_ra_doc_url(html)
            if doc_url:
                print(f"  found first RA Document URL: {doc_url}")
                result = try_download_ra_direct(new_page, doc_url, save_path)
                if result["success"]:
                    new_page.close()
                    return result

            result = _click_ra_document(new_page, save_path)
            new_page.close()
            return result

        if "showradocumentPdf" in current_url:
            print("  page shows PDF directly, attempting to capture response...")
            try:
                with new_page.expect_download(timeout=15000) as download_info:
                    pass
                download = download_info.value
                download.save_as(save_path)
                print(f"  RA PDF saved -> {save_path}")
                new_page.close()
                return {"success": True, "pdfPath": save_path}
            except Exception:
                try:
                    result = try_download_ra_direct(new_page, current_url, save_path)
                    if result["success"]:
                        new_page.close()
                        return result
                except Exception as e:
                    print(f"  failed to capture PDF from showradocumentPdf page: {e}")

        new_page.close()
        return {"success": False, "error": f"Unhandled page type: {current_url}"}

    return {"success": False, "error": "No download or page opened on RA link click"}


def try_download_ra(page, gem_id: str, download_dir: str) -> dict:
    delay(2000)
    link, href = _find_ra_link(page, gem_id)
    if link is None:
        return {"success": False, "error": "RA link not found"}

    save_path = _new_pdf_path(download_dir, gem_id)
    full_url = urljoin("https://bidplus.gem.gov.in", href) if href else None

    if full_url and "list-ra-schedules" in full_url:
        result = try_download_ra_from_schedules_html(page, full_url, save_path)
        if result["success"]:
            return result
        print(f"  schedules HTML approach failed: {result.get('error')}")

    if full_url and "/showradocumentPdf" in full_url:
        result = try_download_ra_direct(page, full_url, save_path)
        if result["success"]:
            return result
        print(f"  direct RA download failed: {result.get('error')}")
        result = try_download_ra_from_schedules_html(page, full_url, save_path)
        if result["success"]:
            return result

    return try_download_ra_via_click(page, link, gem_id, save_path)


def _save_bid_status_to_db(gem_id: str, status: str) -> None:
    if not status:
        return
    try:
        from tender_search.models import TenderMerged
        gem = TenderMerged.objects.filter(referenceno=gem_id).first()
        if not gem:
            print(f"  {gem_id}: TenderMerged not found for status save")
            return
        gem.currentstatus = status.upper()
        gem.save()
        print(f"  {gem_id}: saved currentStatus = {gem.currentstatus}")
    except Exception as e:
        print(f"  {gem_id}: could not save currentStatus — {e}")


def _extract_status_from_page(page, gem_id: str) -> str | None:
    try:
        delay(2000)
        row_info = find_gem_id_result(page, gem_id)
        if not row_info:
            print(f"  {gem_id}: row not found for status extraction")
            return None
        status = row_info.get("bidStatus")
        print(f'  {gem_id}: bid status — "{status}"')
        if status:
            _save_bid_status_to_db(gem_id, status)
        return status
    except Exception as e:
        print(f"  {gem_id}: status extraction failed — {e}")
        return None


def download_ra_pdf(gem_id: str, download_dir: str = r"D:\temp") -> dict:
    chrome_path = os.environ.get("CHROME_PATH") or detect_chrome_path()
    saved_path = None

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            executable_path=chrome_path,
            headless=settings.HEADLESS_BROWSER,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-features=ChromeWhatsNewUI",
            ],
        )
        page = browser.new_page()

        print(f"  {gem_id}: searching ongoing bids...")
        perform_search(page, gem_id, check_bid_ra_status=False)
        if wait_for_search_results(page, gem_id):
            _extract_status_from_page(page, gem_id)
            result = try_download_ra(page, gem_id, download_dir)
            if result["success"]:
                saved_path = result["pdfPath"]
            else:
                print(f"  {gem_id}: ongoing RA download failed, trying with bid/ra status...")
                perform_search(page, gem_id, check_bid_ra_status=True)
                if wait_for_search_results(page, gem_id):
                    _extract_status_from_page(page, gem_id)
                    result = try_download_ra(page, gem_id, download_dir)
                    if result["success"]:
                        saved_path = result["pdfPath"]
        else:
            print(f"  {gem_id}: no data found in ongoing bids, trying with bid/ra status...")
            perform_search(page, gem_id, check_bid_ra_status=True)
            if wait_for_search_results(page, gem_id):
                _extract_status_from_page(page, gem_id)
                result = try_download_ra(page, gem_id, download_dir)
                if result["success"]:
                    saved_path = result["pdfPath"]

    if saved_path:
        print(f"  {gem_id}: uploading to S3...")
        try:
            s3_res = file_storage.upload(saved_path, reference_no=gem_id)
            s3_url = s3_res["url"]
            print(f"  {gem_id}: S3 link: {s3_url}")
        except Exception as e:
            print(f"  {gem_id}: S3 upload failed: {e}")
            s3_url = ""
        # ponytail: drive upload disabled — s3 only
        # drive_res = upload_to_drive(saved_path, folder_id=settings.GOOGLE_DRIVE_FOLDER_ID)
        # drive_url = drive_res.get("webViewLink", "")
        # print(f"  {gem_id}: Drive link: {drive_url}")
        drive_url = ""
        # if not s3_url:
        #     s3_url = drive_url
        save_extraction_to_db(
            referenceno=gem_id,
            file_tag="raDocument",
            file_url=s3_url,
            pdf_path=saved_path,
        )
        return {"success": True, "pdfPath": saved_path, "driveLink": drive_url, "s3Link": s3_url}

    return {"success": False, "error": "Could not download RA PDF"}
