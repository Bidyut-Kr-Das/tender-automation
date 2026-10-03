"""Copied from tender_search/services/gem_ra_pdf_parser.py (parse_ra_document); DB code removed."""
import re
import pdfplumber


def parse_ra_document(pdf_path: str) -> dict:
    start_date = None
    end_date = None

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""

            if start_date is None:
                m = re.search(r"RA\s+Start\s+Date/Time\s*[:]?\s*([\d-]+\s+[\d:]+)", text)
                if m:
                    start_date = m.group(1).strip()

            if end_date is None:
                m = re.search(r"RA\s+End\s+Date/Time\s*[:]?\s*([\d-]+\s+[\d:]+)", text)
                if m:
                    end_date = m.group(1).strip()

            if start_date is not None and end_date is not None:
                break

    return {"start_date": start_date, "end_date": end_date}
