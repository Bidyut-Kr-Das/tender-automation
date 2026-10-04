import logging
import os,json
import re
import tempfile
from datetime import datetime

import openpyxl
import requests
from django.conf import settings

from django.db import transaction
from django.utils import timezone
from pprint import pprint
from tender_search.models import Costingsheetdetails, Items, TenderMerged
from automation_v2.lib.costing_excel_parse import (  # shared with v2
    _extract_drive_file_id,
    _is_drive_link,
    _download_drive_file,
    _find_all_header_rows,
    _find_price_basis,
    _find_applicable_index,
    _parse_table,
)


logger = logging.getLogger(__name__)


@transaction.atomic
def save_costing_to_db(gemid, table_data, price_basis="FIRM", applicable_index=None):
    merged = TenderMerged.objects.filter(referenceno=gemid).first()
    if not merged:
        return {"success": False, "error": f"TenderMerged not found for docketno={gemid}"}

    materials = {}
    for t in table_data:
        for k, v in t.get("materials", {}).items():
            if k not in materials:
                materials[k] = v

    merged.rawmaterials = json.dumps(materials)
    merged.price = price_basis
    if applicable_index:
        merged.applicableindex = applicable_index
    if table_data:
        bd = table_data[0].get("base_date")
        if bd:
            merged.basedate = datetime.combine(bd, datetime.min.time())
    our_value = sum(
        row.get("total_price") or 0
        for t in table_data
        for row in t.get("rows", [])
    )
    merged.ourvalue = str(our_value) if our_value else None
    merged.save()

    all_codes = {
        row.get("item_code")
        for t in table_data
        for row in t.get("rows", [])
        if row.get("item_code")
    }
    schedule_map = dict(
        Items.objects.filter(itemcode__in=all_codes).values_list("itemcode", "itemschedule")
    )

    now = timezone.now()
    for t in table_data:
        for row in t.get("rows", []):
            item_code = (row.get("item_code") or "").strip()
            if not item_code:
                continue
            location = row.get("location") or ""
            obj = Costingsheetdetails.objects.filter(
                tendermergedid=merged, itemcode=item_code, location=location
            ).first()
            if obj is None and not location:
                obj = Costingsheetdetails.objects.filter(
                    tendermergedid=merged, itemcode=item_code
                ).first()
            fields = {
                "proposederpitemname": row.get("item_name"),
                "proposederpquantity": (
                    str(row.get("quantity")) if row.get("quantity") is not None else None
                ),
                "priceoffullquantity": (
                    str(row.get("total_price")) if row.get("total_price") is not None else None
                ),
                "cva": row.get("cva"),
                "location": location,
                "itemschedule": schedule_map.get(item_code),
                "updatedat": now,
            }
            if obj:
                for k, v in fields.items():
                    setattr(obj, k, v)
                obj.save()
            else:
                Costingsheetdetails.objects.create(
                    itemcode=item_code,
                    tendermergedid=merged,
                    createdat=now,
                    **fields,
                )
    return {"success": True}


def _build_laser_cost_payload(table_data, price_basis):
    materials = {}
    for t in table_data:
        for k, v in t.get("materials", {}).items():
            if k not in materials:
                materials[k] = v

    docket_no = None
    costing_sheet_details = []
    for t in table_data:
        if docket_no is None:
            docket_no = t.get("docket_no")
        for row in t.get("rows", []):
            costing_sheet_details.append({
                "proposedErpItemName": row.get("item_name"),
                "proposedQty": row.get("quantity"),
                "cvaValue": row.get("cva"),
            })

    return {
        "docketNo": docket_no,
        "priceBasis": price_basis,
        "rawMaterials": materials,
        "costingSheetDetails": costing_sheet_details,
    }


def _send_to_laser_cost_api(payload):
    url = f"http://{settings.LASER_TENDER_COST_API}/api/costing/parsed"
    headers = {"Authorization": f"Bearer {settings.WORKER_API_KEY}"}
    resp = requests.post(url, json=payload, headers=headers, timeout=60)
    resp.raise_for_status()
    return resp.json()


def parse_costing_excel(gemid, appsheet_link, sender=None):
    temp_dir = tempfile.gettempdir()
    safe_id = str(gemid).replace("/", "-").replace("\\", "-")
    temp_path = os.path.join(temp_dir, f"costing_{safe_id}.xlsx")
    source_is_url = bool(re.match(r"^https?://", str(appsheet_link).strip().lower()))
    downloaded = False

    try:
        if source_is_url:
            if _is_drive_link(appsheet_link):
                file_id = _extract_drive_file_id(appsheet_link)
                if not file_id:
                    return {"gemid": gemid, "error": f"Could not extract Drive file ID from link: {appsheet_link}"}
                _download_drive_file(file_id, temp_path)
                downloaded = True
                source_path = temp_path
            else:
                resp = requests.get(appsheet_link, stream=True, timeout=120)
                resp.raise_for_status()

                content_type = resp.headers.get("Content-Type", "")
                if "html" in content_type.lower():
                    first_200 = resp.content[:200].decode("utf-8", errors="replace")
                    return {"gemid": gemid, "error": f"Expected Excel, got HTML. Preview: {first_200}"}

                # Sniff body even if content-type is octet-stream (Drive sometimes mislabels)
                head = resp.content[:512] if hasattr(resp, "content") else b""
                if head.lstrip().lower().startswith(b"<!doctype html") or b"accounts.google.com" in head.lower():
                    first_200 = head[:200].decode("utf-8", errors="replace")
                    return {"gemid": gemid, "error": f"Expected Excel, got HTML. Preview: {first_200}"}

                with open(temp_path, "wb") as f:
                    f.write(resp.content)
                downloaded = True
                source_path = temp_path
        else:
            source_path = appsheet_link
            if not os.path.exists(source_path):
                return {"gemid": gemid, "error": f"Costing file not found at path: {source_path}"}

        wb = openpyxl.load_workbook(source_path, data_only=True)

        calc_sheets = [ws for ws in wb.worksheets if "AUTO CALCULATION SHEET" in ws.title.upper()]
        if not calc_sheets:
            return {"gemid": gemid, "error": "AUTO CALCULATION SHEET tab not found"}

        tables = []
        for ws in calc_sheets:
            header_rows = _find_all_header_rows(ws)
            if not header_rows:
                continue
            for i, hr in enumerate(header_rows):
                end_row = header_rows[i + 1] if i + 1 < len(header_rows) else ws.max_row + 1
                table = _parse_table(ws, hr, end_row)
                if table:
                    tables.append(table)

        if not tables:
            return {"gemid": gemid, "error": "No valid table headers found (DOCKET NO + PROPOSE ERP)"}

        price_basis = _find_price_basis(calc_sheets[0])
        applicable_index = _find_applicable_index(calc_sheets[0])
        if sender == "laser_cost":
            payload = _build_laser_cost_payload(tables, price_basis)
            pprint(payload)
            _send_to_laser_cost_api(payload)
        else:
            save_costing_to_db(gemid=gemid, table_data=tables, price_basis=price_basis, applicable_index=applicable_index)
        result = {
            "gemid": gemid,
            "tables": tables,
            "price": price_basis,
            "applicableIndex": applicable_index,
            "sender": sender,
        }
        logger.info("Costing parse result for %s: %s", gemid, json.dumps(result, default=str))
        return result

    except Exception as e:
        return {"gemid>>>>": gemid, "error": str(e)}

    finally:
        if downloaded and os.path.exists(temp_path):
            os.remove(temp_path)
