import os
import tempfile
import logging
from datetime import datetime

from django.conf import settings

from automation_v2.lib.downloads import (
    _download_from_drive as download_from_drive,
    _download_from_url as download_from_url,
    _extract_drive_file_id as extract_drive_file_id,
)
from automation_v2.lib.gem_ra_pdf_parser import (  # shared with v2
    parse_ra_document,
)

logger = logging.getLogger(__name__)


def _save_to_db(gemid: str, result: dict):
    try:
        from tender_search.models import TenderMerged
        gem = TenderMerged.objects.filter(referenceno=gemid).first()

        if not gem:
            logger.error("No TenderMerged found for referenceno: %s", gemid)
            return

        start_date = result.get("start_date")
        end_date = result.get("end_date")

        if start_date:
            gem.reverseauctionstartdate = datetime.strptime(start_date, "%d-%m-%Y %H:%M:%S")
        if end_date:
            gem.reverseauctionenddate = datetime.strptime(end_date, "%d-%m-%Y %H:%M:%S")

        if start_date and end_date:
            gem.reverseauctionautomationstatus = "SUCCESS"
        else:
            gem.reverseauctionautomationstatus = None

        gem.save()
        logger.info("Saved RA dates for %s: start=%s end=%s", gemid, start_date, end_date)

    except Exception as e:
        logger.error("Error saving RA dates to DB for %s: %s", gemid, e)


def process_ra_document(reference_no: str, drive_link: str) -> dict:
    result = {
        "reference_no": reference_no,
        "success": False,
        "start_date": None,
        "end_date": None,
        "error": None,
    }

    temp_dir = getattr(settings, "TENDER_PARSING_TEMP_DIR", tempfile.gettempdir())
    safe_name = reference_no.replace("/", "-").replace("\\", "-")
    pdf_path = os.path.join(temp_dir, f"{safe_name}_ra.pdf")

    file_id = extract_drive_file_id(drive_link)

    try:
        if file_id:
            logger.info("Downloading file_id=%s -> %s", file_id, pdf_path)
            download_from_drive(file_id, pdf_path)
        elif drive_link.startswith("http://") or drive_link.startswith("https://"):
            # ponytail: direct tender-document url, bypass Drive; ceiling: no auth, add header if 192.168 requires
            logger.info("Downloading direct URL -> %s : %s", pdf_path, drive_link)
            download_from_url(drive_link, pdf_path)
        else:
            result["error"] = f"Could not extract file ID from Drive link: {drive_link}"
            return result

        logger.info("Parsing RA document for %s...", reference_no)
        parsed = parse_ra_document(pdf_path)
        result["start_date"] = parsed["start_date"]
        result["end_date"] = parsed["end_date"]

        if result["start_date"] is None and result["end_date"] is None:
            result["error"] = "Could not find Start/End Date in RA document"
        else:
            result["success"] = True
            logger.info("Parsed RA document for %s: start=%s end=%s", reference_no, result["start_date"], result["end_date"])

    except Exception as e:
        logger.exception("RA document processing failed")
        result["error"] = str(e)

    finally:
        if os.path.exists(pdf_path):
            try:
                os.remove(pdf_path)
                logger.info("Deleted temp file: %s", pdf_path)
            except Exception as e:
                logger.warning("Could not delete %s: %s", pdf_path, e)

    _save_to_db(reference_no, result)
    return result