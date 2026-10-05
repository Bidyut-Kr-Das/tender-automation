import os
from playwright.sync_api import sync_playwright
from automation_v2.lib.file_storage import file_storage
from .gem_pdf_parser_ai import save_extraction_to_db
from .gem_bid_results import find_gem_id_result
from django.conf import settings

from automation_v2.lib.browser import delay, detect_chrome_path
from automation_v2.lib.gem_ra_pdf_downloader import (  # shared with v2
    perform_search,
    wait_for_search_results,
    try_download_ra,
)


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
