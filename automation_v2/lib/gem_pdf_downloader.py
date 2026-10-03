"""Copied from tender_search/services/gem_pdf_downloader.py (detect_chrome_path, perform_search, wait_for_search_results, try_download, delay); DB code removed."""
import os
import time
from urllib.parse import urljoin
from django.conf import settings


def delay(ms: int) -> None:
    time.sleep(ms / 1000)


def detect_chrome_path() -> str:
    # Prefer path provided through environment variable
    chrome_path = settings.CHROME_PATH

    if chrome_path:
        if os.path.exists(chrome_path):
            return chrome_path

        raise FileNotFoundError(
            f"Chrome executable not found at CHROME_PATH: {chrome_path}"
        )

    # Fallback for local Windows development
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files\Chromium\Application\chrome.exe",
    ]

    for p in candidates:
        if os.path.exists(p):
            return p

    raise FileNotFoundError(
        "Chrome not found. Set the CHROME_PATH environment variable."
    )


def perform_search(page, gem_id: str, check_bid_ra_status: bool = False) -> None:
    page.goto("https://bidplus.gem.gov.in/all-bids", wait_until="networkidle")
    page.locator("#searchBid").fill(gem_id, timeout=20000)
    delay(1000)

    search_dropdown = page.locator("button.dropdown-toggle.searchtype")
    if search_dropdown.count() > 0:
        search_dropdown.click()
        delay(500)
        exact_option = page.locator("ul.dropdown-menu a, ul.dropdown-menu li").filter(
            has_text="Exact"
        ).first
        if exact_option.count() > 0:
            exact_option.click()
    delay(1000)

    if check_bid_ra_status:
        checkbox = page.locator(
            "label:has-text('BID/RA STATUS') input[type='checkbox']"
        ).first
        if checkbox.count() > 0 and not checkbox.is_checked():
            checkbox.click()
        delay(1000)

    page.locator("#searchBidRA").click()


def wait_for_search_results(page, gem_id: str, timeout: int = 15000) -> bool:
    try:
        page.locator("a.bid_no_hover").filter(has_text=gem_id).wait_for(
            timeout=timeout, state="attached"
        )
        return True
    except Exception:
        body_text = page.locator("body").inner_text()
        if "No data found" in body_text:
            return False
        start = time.time() * 1000
        while (time.time() * 1000) - start < timeout:
            if gem_id in page.locator("body").inner_text():
                return True
            delay(1000)
        return False


def try_download(page, gem_id: str, download_dir: str) -> dict:
    delay(2000)
    link = page.locator("a.bid_no_hover").filter(has_text=gem_id).first
    if link.count() == 0:
        return {"success": False, "error": "Bid link not found"}

    href = link.get_attribute("href")
    if not href:
        return {"success": False, "error": "No href on bid link"}

    full_url = urljoin("https://bidplus.gem.gov.in", href)
    safe_name = gem_id.replace("/", "-")
    os.makedirs(download_dir, exist_ok=True)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    save_path = os.path.join(download_dir, f"{safe_name}_{timestamp}.pdf")

    print(f"  {gem_id}: downloading from {full_url}")
    response = page.request.get(full_url)
    if not response.ok:
        return {"success": False, "error": f"HTTP {response.status}"}

    body = response.body()
    if len(body) < 100:
        return {"success": False, "error": f"File too small ({len(body)} bytes)"}

    with open(save_path, "wb") as f:
        f.write(body)
    print(f"  {gem_id}: PDF saved → {save_path} ({len(body)} bytes)")
    return {"success": True, "pdfPath": save_path}
