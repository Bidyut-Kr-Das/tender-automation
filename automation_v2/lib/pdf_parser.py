"""No DB code; used by both automation_v2 and tender_search."""
import os
import pdfplumber
import re


def clean_text(text):
    # Safely handle None values from empty/merged PDF cells
    if text is None or str(text).strip() == "None":
        return ""
    # Remove newlines and excess spaces
    return re.sub(r'\s+', ' ', str(text)).strip()


def parse_item_categories(raw_text):
    """
    Smartly splits the GeM Item Category string based on specific prefixes.
    """
    if not raw_text:
        return []
    
    raw_parts = raw_text.split(" , ")
    clean_items = []
    
    for part in raw_parts:
        part = part.strip()
        if not part: 
            continue
            
        if not clean_items:
            clean_items.append(part)
        else:
            # Added "XLPE" and other dynamic starts to catch different cable/item names
            if re.match(r'^(Supply|360|Gasket|Air|XLPE|[\d\.]+mtr|1 X)', part, re.IGNORECASE):
                clean_items.append(part)
            else:
                # Append back to previous item (it's an internal comma)
                clean_items[-1] += " , " + part
                
    return clean_items


def parse_gem_pdf_service(pdf_path):
    """
    Core service function to parse the GeM PDF and return structured dictionary data.
    """
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"The file {pdf_path} does not exist.")

    data = {
        "Total_Quantity": None,
        "Item_Category_String": None,
        "Item_Category_List": [],
        "EMD_Details": {},
        "Dated": None,
        "Reverse_Auction_Applicable": False,
        "Empanelled_Inspection_Agency": None,
        "Technical_Specifications": [],
        "Consignees": []
    }

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text() or ""
            if not data["Dated"]:
                m = re.search(r'[Dd]ated\s*:?\s*(\d{2}-\d{2}-\d{4})', page_text)
                if m:
                    data["Dated"] = m.group(1)
            if not data["Reverse_Auction_Applicable"] and "reverse auction would be conducted" in page_text.lower():
                data["Reverse_Auction_Applicable"] = True
            tables = page.find_tables()
            
            for table in tables:
                extracted_text = table.extract()
                
                if not extracted_text:
                    continue
                
                # --- 1. BID DETAILS ---
                for row in extracted_text:
                    if not row or not row[0]: 
                        continue
                    
                    header = clean_text(row[0]) 
                    
                    if "Total Quantity" in header or "कुल मात्रा" in header:
                        if len(row) > 1:
                            data["Total_Quantity"] = clean_text(row[1])
                            
                    elif "Item Category" in header or "वस्तु श्रेणी" in header:
                        if len(row) > 1:
                            cat_text = clean_text(row[1])
                            data["Item_Category_String"] = cat_text
                            data["Item_Category_List"] = parse_item_categories(cat_text)
                        
                    # --- 2. EMD DETAILS ---
                    elif "Advisory Bank" in header or "एडवाइजरी बैंक" in header:
                        if len(row) > 1:
                            data["EMD_Details"]["Advisory Bank"] = clean_text(row[1])
                    elif "EMD Amount" in header or "ईएमडी राशि" in header:
                        if len(row) > 1:
                            data["EMD_Details"]["EMD Amount"] = clean_text(row[1])
                    elif "Empanelled Inspection" in header or "Inspection Agency" in header or "निरीक्षण एजेंसी" in header:
                        if len(row) > 1:
                            data["Empanelled_Inspection_Agency"] = clean_text(row[1])
                # --- 3. TECHNICAL SPECIFICATIONS (Single item / 3-Column or 2-Column Key-Value style) ---
                if len(extracted_text) > 0 and extracted_text[0]:
                    header_row = [clean_text(c) for c in extracted_text[0]]
                    header_string = "".join(header_row)
                    
                    if "Specification Name" in header_string or "विशिष्टि का नाम" in header_string:
                        
                        group_idx, name_idx, val_idx = -1, -1, -1
                        
                        # Dynamically find the columns
                        for idx, col_name in enumerate(header_row):
                            if "Specification Name" in col_name or "विशिष्टि का नाम" in col_name:
                                name_idx = idx
                            elif "Allowed Values" in col_name or "अनुमत मूल्य" in col_name or "Bid Requirement" in col_name:
                                val_idx = idx
                            elif ("विवरण" in col_name or "Specification" in col_name) and "Name" not in col_name:
                                group_idx = idx
                                
                        item_idx = len(data["Technical_Specifications"])
                        item_name = data["Item_Category_List"][item_idx] if item_idx < len(data["Item_Category_List"]) else "Unknown Item"

                        # Scenario A: It has all 3 Columns (Group, Name, Value)
                        if name_idx != -1 and val_idx != -1 and group_idx != -1:
                            tech_spec = {}
                            current_group = "General Parameters" # Fallback
                            
                            for row in extracted_text[1:]:
                                if row and len(row) > max(name_idx, val_idx, group_idx):
                                    g_val = clean_text(row[group_idx])
                                    k_val = clean_text(row[name_idx])
                                    v_val = clean_text(row[val_idx])
                                    
                                    # FORWARD FILLING: If group cell isn't empty, update the current group
                                    if g_val:
                                        current_group = g_val
                                        
                                    # If Key exists, add it to the nested dictionary
                                    if k_val:
                                        if current_group not in tech_spec:
                                            tech_spec[current_group] = {}
                                        tech_spec[current_group][k_val] = v_val
                                        
                            if tech_spec:
                                data["Technical_Specifications"].append({
                                    "Item_Name": item_name,
                                    "Type": "Grouped-Key-Value", 
                                    "Data": tech_spec
                                })
                                
                        # Scenario B: It only has 2 columns (Name, Value)
                        elif name_idx != -1 and val_idx != -1:
                            tech_spec = {}
                            for row in extracted_text[1:]:
                                if row and len(row) > max(name_idx, val_idx):
                                    k_val = clean_text(row[name_idx])
                                    v_val = clean_text(row[val_idx])
                                    if k_val:
                                        tech_spec[k_val] = v_val
                                        
                            if tech_spec:
                                data["Technical_Specifications"].append({
                                    "Item_Name": item_name,
                                    "Type": "Flat-Key-Value", 
                                    "Data": tech_spec
                                })

                # --- 4. TECHNICAL SPECIFICATIONS (Multi-item Links style) ---
                if len(extracted_text) >= 2 and extracted_text[0] and extracted_text[0][0]:
                    if "Specification Document" in clean_text(extracted_text[0][0]) or "Buyer Specification Document" in clean_text(extracted_text[0][0]):
                        
                        item_idx = len(data["Technical_Specifications"])
                        item_name = data["Item_Category_List"][item_idx] if item_idx < len(data["Item_Category_List"]) else "Unknown Item"

                        table_bbox = table.bbox 
                        links_in_table = []
                        
                        for link in page.hyperlinks:
                            cx = (link['x0'] + link['x1']) / 2
                            cy = (link['top'] + link['bottom']) / 2
                            if (table_bbox[0] <= cx <= table_bbox[2] and table_bbox[1] <= cy <= table_bbox[3]):
                                links_in_table.append(link)
                        
                        links_in_table = sorted(links_in_table, key=lambda l: l['top'])
                        
                        spec_link = links_in_table[0]['uri'] if len(links_in_table) > 0 else None
                        boq_link = links_in_table[1]['uri'] if len(links_in_table) > 1 else None
                        
                        data["Technical_Specifications"].append({
                            "Item_Name": item_name,
                            "Type": "Document Links",
                            "Specification_Document_Link": spec_link,
                            "BOQ_Document_Link": boq_link
                        })

                # --- 5. CONSIGNEES / QUANTITY TABLE ---
                if len(extracted_text) > 0 and extracted_text[0]:
                    col_2 = extracted_text[0][1] if len(extracted_text[0]) > 1 else ""
                    if col_2 and ("Consignee" in clean_text(col_2) or "परेषिती" in clean_text(col_2)):
                        
                        item_idx = len(data["Consignees"])
                        item_name = data["Item_Category_List"][item_idx] if item_idx < len(data["Item_Category_List"]) else "Unknown Item"

                        consignee_list = []
                        for row in extracted_text[1:]:
                            if row and len(row) >= 5:
                                name = clean_text(row[1])
                                if not name:
                                    continue 

                                consignee_list.append({
                                    "S_No": clean_text(row[0]),
                                    "Consignee_Name": name,
                                    "Address": clean_text(row[2]),
                                    "Quantity": clean_text(row[3]),
                                    "Delivery_Days": clean_text(row[4])
                                })
                        
                        if consignee_list:
                            data["Consignees"].append({
                                "Item_Name": item_name,
                                "Consignee_Data": consignee_list
                            })
    return data
