import os
from tender_search.models import TenderMerged, TenderFiles
from django.utils import timezone


def save_extraction_to_db(
    referenceno: str,
    file_tag: str,
    file_url: str,
    pdf_path: str = "",
    item_category: str = "",
    total_quantity: str = "",
    size: str = None,
    reportings: list = None,
) -> dict:
    """Save extraction results to TenderFiles. No OpenAI calls."""
    try:
        tender = TenderMerged.objects.get(referenceno=referenceno)
    except TenderMerged.DoesNotExist:
        print(f"  [DB] TenderMerged not found for {referenceno}")
        return {"success": False, "error": f"TenderMerged not found for {referenceno}"}

    try:
        # Create TenderFiles entry
        if file_url:
            TenderFiles.objects.create(
                tendermergedid=tender,
                name=os.path.basename(pdf_path),
                extension="pdf",
                url=file_url,
                tags=[file_tag],
                createdat=timezone.now(),
                updatedat=timezone.now(),

            )

        print(f"  [DB] Saved extraction for {referenceno}")
        return {"success": True}

    except Exception as e:
        tender.parsestatus = "FAILED"
        tender.parseerror = str(e)
        tender.save()
        print(f"  [DB] FAILED for {referenceno}: {e}")
        return {"success": False, "error": str(e)}
