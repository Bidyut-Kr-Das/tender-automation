import os
import json
from tender_search.models import TenderMerged, Reportings, TenderFiles
from django.utils import timezone
from datetime import datetime
from automation_v2.lib.pdf_parser import (  # shared with v2
    parse_gem_pdf_service,
)


def _filename_to_gem_id(filename: str) -> str:
    base = os.path.splitext(os.path.basename(filename))[0]
    gem_part = base.split('_')[0]           # "GEM-2026-B-7724560"
    return gem_part.replace('-', '/') 

def _build_tech_spec_markdown(spec: dict) -> str:
    item_name = spec.get("Item_Name", "Unknown Item")
    lines = [f"## {item_name}", "", "| Specification | Specification Name | Bid Requirement |", "|---|---|---|"]
    data = spec.get("Data", {})
    if spec["Type"] in ("Key-Value", "Flat-Key-Value"):
        for k, v in data.items():
            lines.append(f"| General Parameters | {k} | {v} |")
    elif spec["Type"] == "Grouped-Key-Value":
        for group, items in data.items():
            for k, v in items.items():
                lines.append(f"| {group} | {k} | {v} |")
    return "\n".join(lines)

def _save_to_db(gem_id: str, data: dict) -> dict:
    
    try:
        tender = TenderMerged.objects.get(referenceno=gem_id)
        print("..............")
    except TenderMerged.DoesNotExist:
        return {"success": False, "error": f"TenderMerged not found for {gem_id}"}
    try:
        print(f"\n  [DB] Saving to TenderMerged ({gem_id}):")
        print(f"    totalquantity = {data.get('Total_Quantity')}")
        print(f"    inspectionagency = {data.get('Empanelled_Inspection_Agency')}")
        print(f"    itemcategory  = {data.get('Item_Category_String')}")
        print(f"    emd           = {json.dumps(data.get('EMD_Details', {}), ensure_ascii=False)}")
        if data.get("Total_Quantity"):
            tender.totalquantity = str(data["Total_Quantity"])
        if data.get("Item_Category_String"):
            tender.itemcategory = str(data["Item_Category_String"])
        emd_details = data.get("EMD_Details") or {}
        if emd_details.get("Advisory Bank"):
            tender.beneficiarybankdetails = emd_details["Advisory Bank"]
        if emd_details.get("EMD Amount"):
            tender.emd = emd_details["EMD Amount"]
        if data.get("Dated"):
            tender.publisheddate = datetime.strptime(data["Dated"], "%d-%m-%Y")
        if data.get("Empanelled_Inspection_Agency"):
            tender.inspectionagency = str(data["Empanelled_Inspection_Agency"])
        has_links = False
        size_md_parts = []
        seen_urls = set()
        for spec in data.get("Technical_Specifications", []):
            if spec["Type"] == "Document Links":
                has_links = True
                item_name = spec.get("Item_Name", "Unknown")
                print(f"  [DB] TenderFiles: {item_name}")
                spec_url = spec.get("Specification_Document_Link")
                if spec_url and spec_url not in seen_urls:
                    seen_urls.add(spec_url)
                    print(f"    -> {item_name}: Specification Document = {spec_url}")
                    TenderFiles.objects.create(tendermergedid=tender, name=f"{item_name}: Specification Document", extension=spec_url.split(".")[-1], url=spec_url, source="gem", tags=["SPECIFICATION_DOCUMENT"], createdat=timezone.now(), updatedat=timezone.now())
                boq_url = spec.get("BOQ_Document_Link")
                if boq_url and boq_url not in seen_urls:
                    seen_urls.add(boq_url)
                    print(f"    -> {item_name}: BOQ Document = {boq_url}")
                    TenderFiles.objects.create(tendermergedid=tender, name=f"{item_name}: BOQ Document", extension=boq_url.split(".")[-1], url=boq_url, source="gem", tags=["BOQ_DOCUMENT"], createdat=timezone.now(), updatedat=timezone.now())
            else:
                md = _build_tech_spec_markdown(spec)
                if md:
                    size_md_parts.append(md)

        if has_links:
            print(f"  [DB] TenderMerged.size = 'External Links'")
            tender.size = "External Links"
        elif size_md_parts:
            size_text = "\n\n".join(size_md_parts)
            print(f"  [DB] TenderMerged.size (markdown):\n{size_text}")
            tender.size = size_text

        print(f"  [DB] Reportings:")
        for group in data.get("Consignees", []):
            for c in group.get("Consignee_Data", []):
                print(f"    officer={c.get('Consignee_Name','')}, address={c.get('Address','')}, quantity={c.get('Quantity','')}")
                Reportings.objects.create(tendermergedid=tender, officer=c.get("Consignee_Name", ""), address=c.get("Address", ""), quantity=c.get("Quantity", ""), createdat=timezone.now(), updatedat=timezone.now())
        if data.get("Reverse_Auction_Applicable"):
            tender.reverseauctionapplicable = True
        tender.parsestatus = "COMPLETED"
        tender.parseerror = None
        tender.save()
        print(f"  [DB] Done — all saved successfully\n")
        return {"success": True}
    except Exception as e:
        tender.parsestatus = "FAILED"
        tender.parseerror = str(e)
        tender.save()
        print(f"  [DB] FAILED: {e}\n")
        return {"success": False, "error": str(e)}

    
def parse_and_save_gem_pdf(pdf_path: str) -> dict:
    # print(pdf_path)
    gem_id = _filename_to_gem_id(pdf_path)
    # print(gem_id)
    parsed = parse_gem_pdf_service(pdf_path)
    # print(parsed)
    db_result = _save_to_db(gem_id=gem_id, data=parsed)
    return {"gem_id": gem_id, "parsed_data": parsed, "db_save": db_result}

