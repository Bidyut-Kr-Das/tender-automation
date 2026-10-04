"""No DB code; used by both automation_v2 and tender_search."""
import re
from typing import Optional
from playwright.sync_api import Page


def find_gem_id_result(page: Page, gem_id: str) -> Optional[dict]:
    link = page.locator("a.bid_no_hover").filter(has_text=gem_id)
    link_count = link.count()

    if link_count == 0:
        body_text = page.locator("body").inner_text()
        if gem_id in body_text:
            status_match = re.search(
                r"Status\s*:\s*([^\n]+)", body_text, re.IGNORECASE
            )
            return {
                "bidStatus": status_match.group(1).strip() if status_match else None,
            }
        return None

    block_header = page.locator(
        f"xpath=//a[contains(@class, 'bid_no_hover') and contains(text(), '{gem_id}')]"
        f"/ancestor::div[contains(@class, 'block_header')]"
    ).first

    bid_status = None
    if block_header.count() > 0:
        status_span = block_header.locator(
            "span.text-success, span.text-danger, span.text-warning"
        ).first
        if status_span.count() > 0:
            text = status_span.inner_text().strip()
            if text:
                bid_status = text

    if not bid_status:
        text_source = (
            block_header.inner_text()
            if block_header.count() > 0
            else page.locator("body").inner_text()
        )
        status_match = re.search(
            r"Status\s*:\s*([^\n]+)", text_source, re.IGNORECASE
        )
        if status_match:
            bid_status = status_match.group(1).strip()

    return {
        "bidStatus": bid_status,
    }
