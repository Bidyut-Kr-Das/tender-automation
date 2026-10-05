import os
from playwright.sync_api import sync_playwright
from automation_v2.lib.file_storage import file_storage
from .gem_pdf_parser_ai import save_extraction_to_db
from django.conf import settings

from automation_v2.lib.browser import detect_chrome_path
from automation_v2.lib.gem_pdf_downloader import (  # shared with v2
    perform_search,
    wait_for_search_results,
    try_download,
)


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