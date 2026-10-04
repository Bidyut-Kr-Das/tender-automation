"""Copied from tender_search/services/gem_ra_pdf_downloader.py (try_download_ra); DB code removed.
Search helpers come from gem_pdf_downloader; fetch.py reaches them through this module."""
import os
import re
import time
from urllib.parse import urljoin

from .browser import delay, detect_chrome_path  # noqa: F401
from .gem_pdf_downloader import perform_search  # noqa: F401
from .gem_pdf_downloader import wait_for_search_results as _wait_for_search_results


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
