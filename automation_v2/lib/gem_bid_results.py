"""Copied from tender_search/services/gem_bid_results.py (find_gem_id_result); DB code removed."""
import re
from typing import Callable, Optional
from playwright.sync_api import sync_playwright, Page, TimeoutError as PwTimeoutError


def _has_view_bid_results_button(page: Page) -> bool:
    patterns = re.compile(
        r"VIEW\s+BID\s+RESULTS|VIEW\s+BID|VIEW\s+RESULT|BID\s+RESULTS",
        re.IGNORECASE,
    )

    for sel in [
        "a",
        "button",
        'input[type="button"]',
        'input[type="submit"]',
        '[role="button"]',
        "[onclick]",
    ]:
        if page.locator(sel).filter(has_text=patterns).count() > 0:
            return True

    non_span = page.locator("*:not(span)").filter(
        has_text=re.compile(r"VIEW\s+BID\s+RESULTS", re.IGNORECASE)
    )
    if non_span.count() > 0:
        return True

    onclick_view = page.locator("[onclick]").filter(
        has_text=re.compile(r"\bVIEW\b", re.IGNORECASE)
    )
    if onclick_view.count() > 0:
        return True

    return False


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
                "hasViewBidResults": _has_view_bid_results_button(page),
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
        "hasViewBidResults": _has_view_bid_results_button(page),
    }
