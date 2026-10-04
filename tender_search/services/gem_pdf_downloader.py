import os
import time
from urllib.parse import urljoin
from playwright.sync_api import sync_playwright
from .file_storage import file_storage
from .gem_pdf_parser_ai import save_extraction_to_db
from django.conf import settings

from .browser import delay, detect_chrome_path


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


def wait_for_search_results(page, gem_id: str, timeout: int = 15000, selector: str = "a.bid_no_hover") -> bool:
    try:
        page.locator(selector).filter(has_text=gem_id).first.wait_for(
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


def download_gem_pdf(gem_id: str, download_dir: str = r"D:\temp") -> dict:
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

        # Attempt 1: Search WITHOUT bid/ra (ongoing only)
        print(f"  {gem_id}: searching ongoing bids...")
        perform_search(page, gem_id, check_bid_ra_status=False)
        if wait_for_search_results(page, gem_id):
            result = try_download(page, gem_id, download_dir)
            if result["success"]:
                saved_path = result["pdfPath"]
            else:
                print(f"  {gem_id}: ongoing download failed, trying bid/ra...")
                perform_search(page, gem_id, check_bid_ra_status=True)
                if wait_for_search_results(page, gem_id):
                    result = try_download(page, gem_id, download_dir)
                    if result["success"]:
                        saved_path = result["pdfPath"]
        else:
            print(f"  {gem_id}: no data found in ongoing bids")
            # Attempt 2: Search WITH bid/ra status
            print(f"  {gem_id}: searching with bid/ra status...")
            perform_search(page, gem_id, check_bid_ra_status=True)
            if wait_for_search_results(page, gem_id):
                result = try_download(page, gem_id, download_dir)
                if result["success"]:
                    saved_path = result["pdfPath"]

    # Browser closed. AI + Drive + DB calls here.
    if saved_path:
        # print(f"  {gem_id}: running AI extraction...")
        # ai_res = extract_pdf_data(pdf_path=saved_path, gem_id=gem_id)

        print(f"  {gem_id}: uploading to S3...")
        try:
            s3_res = file_storage.upload(saved_path, reference_no=gem_id)
            s3_url = s3_res["url"]
            print(f"  {gem_id}: S3 link: {s3_url}")
        except Exception as e:
            print(f"  {gem_id}: S3 upload failed: {e}")
            s3_url = ""
        # ponytail: drive upload disabled — s3 only
        # drive_res = upload_to_drive(saved_path,folder_id=settings.GOOGLE_DRIVE_FOLDER_ID)
        # drive_url = drive_res.get("webViewLink", "")
        # print(f"  {gem_id}: Drive link: {drive_url}")
        drive_url = ""
        # if not s3_url:
        #     s3_url = drive_url
        save_extraction_to_db(referenceno=gem_id,
            file_tag="tenderDocument",
            file_url=s3_url,
            pdf_path=saved_path
              )

        # if ai_res["success"]:
        #     data = ai_res["data"]
        #     size_text = "\n\n".join(
        #         f"### {s['itemCategory']}\n{s['TechnicalSpecifications']}"
        #         for s in data.get("size", [])
        #     ) or None

            
        return {"success": True, "pdfPath": saved_path, "driveLink": drive_url, "s3Link": s3_url}

    return {"success": False, "error": "Could not download PDF"}