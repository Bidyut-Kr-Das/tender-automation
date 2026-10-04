"""Copied from tender_search/services/tender_tiger.py (login_tiger); DB code removed."""
import logging
from pathlib import Path
from playwright.sync_api import sync_playwright
from django.conf import settings
from .browser import detect_chrome_path
from .zip_utils import extract_and_upload
logger = logging.getLogger(__name__)


def _tiger_login(page, email: str, password: str) -> bool:
    print(f"[Tiger] Navigating to login page...")
    page.goto(
        "https://www.tendertiger.com/User/Account?login",
        wait_until="networkidle",
        timeout=30000,
    )
    page.locator('input[name="Email"]').fill(email)
    page.locator('input[name="Password"]').fill(password)
    page.locator("#btnlogin").click()
    page.wait_for_timeout(5000)
    return "dashboard" in page.url.lower()


def login_tiger(email: str, password: str, reference_no: str) -> dict:
    # ponytail: single browser per call, re-login each task — add persistent context if throughput matters
    chrome_path = detect_chrome_path()
    zip_path = None
    result_data = {}

    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=chrome_path, headless=settings.HEADLESS_BROWSER)
        page = browser.new_page()

        try:
            success = _tiger_login(page, email, password)

            if success:
                detail_page = _search_by_reference(page, reference_no)
                zip_path = _download_docs(detail_page, reference_no)

            result_data = {"success": success}
        except Exception as e:
            logger.exception("[Tiger] failed for %s: %s", reference_no, e)
            print(f"[Tiger] ERROR: {e}")
            result_data = {"success": False, "error": str(e)}
        finally:
            browser.close()

    if zip_path and result_data.get("success"):
        try:
            s3_list = extract_and_upload(zip_path, reference_no)
        except Exception as e:
            print(f"[Tiger] Extract/upload failed: {e}")
            s3_list = []
        result_data["s3_list"] = s3_list

    return result_data


def _search_by_reference(page, reference_no: str):
    print(f"[Tiger] Searching dashboard for reference {reference_no!r}...")
    print(f"[Tiger] Redirecting to homepage https://www.tendertiger.com/ ...")
    page.goto("https://www.tendertiger.com/", wait_until="networkidle", timeout=30000)
    page.wait_for_timeout(2000)
    print(f"[Tiger] Clicking Old Search link...")
    # ponytail: 6 dupes — first was hidden, pull-right variants (nth 4/5) are desktop visible
    candidates = page.locator("a.home-link.old-search:has-text('Old Search')")
    clicked = False
    for idx in [4, 5, 0, 1, 2, 3]:
        if idx >= candidates.count():
            continue
        loc = candidates.nth(idx)
        try:
            if loc.is_visible():
                print(f"[Tiger] Trying Old Search nth({idx})...")
                loc.click()
                page.wait_for_timeout(2000)
                # verify search input appeared
                if page.locator("input#txtadvanceSearchMain").is_visible():
                    clicked = True
                    break
        except Exception:
            continue
    if not clicked:
        # fallback: try pull-right specific then first
        old_search = page.locator("a.home-link.pull-right.old-search:has-text('Old Search')").first
        if old_search.count() > 0:
            old_search.wait_for(state="visible", timeout=15000)
            old_search.click()
            page.wait_for_timeout(2000)
        else:
            old_search = page.locator("a.home-link.old-search:has-text('Old Search')").first
            old_search.wait_for(state="visible", timeout=15000)
            old_search.click()
            page.wait_for_timeout(2000)
    print(f"[Tiger] Filling reference in txtadvanceSearchMain: {reference_no}")
    # ponytail: match multiple attrs to avoid ambiguity — id + name + placeholder
    search_input = page.locator("input#txtadvanceSearchMain[name='txtadvanceSearchMain'][placeholder*='keyword']")
    search_input.wait_for(state="visible", timeout=15000)
    search_input.fill(reference_no)
    page.wait_for_timeout(500)
    print(f"[Tiger] Clicking Search button...")
    # ponytail: id duped 2x — header FnSearchTender('header') vs main FnSearchTenders() — pick main
    search_candidates = page.locator("a#advancesearchchk.search_btn.old-Search-btn:has-text('Search')")
    search_clicked = False
    for s_idx in [1, 0]:
        if s_idx >= search_candidates.count():
            continue
        loc = search_candidates.nth(s_idx)
        try:
            if loc.is_visible():
                onclick = loc.get_attribute("onclick") or ""
                print(f"[Tiger] Trying Search nth({s_idx}) onclick={onclick!r}...")
                loc.click()
                search_clicked = True
                break
        except Exception:
            continue
    if not search_clicked:
        # fallback specific — type=button + FnSearchTenders plural is main search
        search_btn = page.locator("a#advancesearchchk[type='button'][onclick*='FnSearchTenders']:has-text('Search')").first
        if search_btn.count() == 0:
            search_btn = page.locator("a#advancesearchchk.search_btn.old-Search-btn:has-text('Search')").first
        search_btn.wait_for(state="visible", timeout=15000)
        search_btn.click()
    page.wait_for_timeout(3000)
    page.wait_for_load_state("networkidle", timeout=30000)
    return _open_matching_tender(page, reference_no)


def _open_matching_tender(page, reference_no: str):
    print(f"[Tiger] Opening tender {reference_no!r} in a new tab...")

    index = page.evaluate(
        """(referenceNo) => {
            const items = document.querySelectorAll('#myScroll li.tender-listing');
            for (let i = 0; i < items.length; i++) {
                const input = items[i].querySelector('input.form-check-input[data-tenderdata]');
                if (!input) continue;
                try {
                    const data = JSON.parse(input.dataset.tenderdata);
                    if ((data.tenderrefno || '').toLowerCase() === referenceNo.toLowerCase()) {
                        return i;
                    }
                } catch (e) {}
            }
            return -1;
        }""",
        reference_no,
    )

    if index == -1:
        print(f"[Tiger] No exact reference match found; using first result.")
        index = 0

    links = page.locator("#myScroll li.tender-listing a[href*='TenderDetail']")
    if links.count() == 0:
        raise RuntimeError("No tender detail link found in search results.")

    link = links.nth(index)
    with page.context.expect_page(timeout=30000) as new_page_info:
        link.click()
    new_page = new_page_info.value
    new_page.wait_for_load_state("networkidle", timeout=30000)
    new_page.wait_for_timeout(3000)
    return new_page


def _download_docs(detail_page, reference_no: str) -> Path:
    print(f"[Tiger] Downloading all documents for {reference_no!r}...")

    # ponytail: 2 variants — old GetTenderDocs vs new DownloadAllFiles btn-download-all-compact
    selectors = [
        "a.btn-download-all-compact:has-text('Download All')",
        "a[onclick*='DownloadAllFiles']:has-text('Download All')",
        ".all-doc-dow a[href*='GetTenderDocs']",
        "a:has-text('Download All')",
    ]
    link = None
    for sel in selectors:
        cand = detail_page.locator(sel).first
        try:
            if cand.count() > 0 and cand.is_visible():
                print(f"[Tiger] Found download button via {sel!r}")
                link = cand
                break
        except Exception:
            continue
    if link is None:
        # fallback strict wait on most likely
        link = detail_page.locator("a.btn-download-all-compact:has-text('Download All')").first
        if link.count() == 0:
            link = detail_page.locator("a[onclick*='DownloadAllFiles']").first
    link.wait_for(state="visible", timeout=30000)

    download_dir = Path(settings.TENDER_PARSING_TEMP_DIR)
    download_dir.mkdir(parents=True, exist_ok=True)
    file_path = download_dir / f"{reference_no}.zip"

    with detail_page.expect_download(timeout=60000) as download_info:
        link.click()
    download = download_info.value
    download.save_as(str(file_path))
    print(f"[Tiger] Downloaded: {file_path}")
    return file_path
