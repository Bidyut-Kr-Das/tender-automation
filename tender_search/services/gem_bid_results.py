import os
import re
import time
from typing import Callable, Optional
from urllib.parse import urljoin

from django.conf import settings
from playwright.sync_api import sync_playwright, Page, TimeoutError as PwTimeoutError

from .browser import delay, detect_chrome_path


def _parse_price(val):
    if not val:
        return 0.0
    cleaned = re.sub(r"[^0-9.]", "", val)
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def _save_to_db(gem_id: str, result: dict):
    try:
        from tender_search.models import TenderMerged
        gem = TenderMerged.objects.get(referenceno=gem_id)
    except Exception as e:
        print(f"  [DB] Could not save {gem_id} — {e}")
        try:
            gem = TenderMerged.objects.get(referenceno=gem_id)
            gem.result_automation_status = "failed"
            gem.result_automation_error = str(e)
            gem.save()
        except Exception:
            pass
        return

    evaluations = result.get("evaluations", [])
    bid_status = result.get("bidStatus", "")

    gem.bidstatus = bid_status
    gem.buyerdetails = result.get("buyerDetails", "{}")

    if evaluations:
        md = [
            "| Rank | Seller Name | Offered Item | Total Price | Status |",
            "|------|-------------|--------------|-------------|--------|",
        ]
        for e in evaluations:
            md.append(
                f"| {e.get('rank', '')} "
                f"| {e.get('sellerName', '')} "
                f"| {e.get('offeredItem', '')} "
                f"| {e.get('totalPrice', '')} "
                f"| {e.get('status', '')} |"
            )
        gem.competitors = "\n".join(md)

    rank1 = rank2 = laser = None
    for e in evaluations:
        r = (e.get("rank") or "").upper()
        if r in ("L1", "1"):
            rank1 = e
        elif r in ("L2", "2"):
            rank2 = e
        if "LASER POWER & INFRA" in (e.get("sellerName") or "").upper():
            laser = e

    if rank1:
        gem.nameofrank1 = rank1.get("sellerName", "")
        gem.valueofrank1 = re.sub(r"[^0-9.]", "", rank1.get("totalPrice", ""))
        if laser:
            p1 = _parse_price(rank1.get("totalPrice"))
            pl = _parse_price(laser.get("totalPrice"))
            if p1 and pl:
                gem.differencebetweenrank1 = f"{((pl - p1) / p1) * 100:.2f}%"

    if rank2:
        gem.nameofrank2 = rank2.get("sellerName", "")
        gem.valueofrank2 = re.sub(r"[^0-9.]", "", rank2.get("totalPrice", ""))
        if laser:
            p2 = _parse_price(rank2.get("totalPrice"))
            pl = _parse_price(laser.get("totalPrice"))
            if p2 and pl:
                gem.differencebetweenrank2 = f"{((pl - p2) / p2) * 100:.2f}%"
            laser_rank = (laser.get("rank") or "").strip()
            gem.ourrank = re.sub(r"[^0-9]", "", laser_rank)
            gem.ourvalue =  laser.get("totalPrice")

    gem.result_automation_status = "completed"
    gem.result_automation_error = ""
    print(gem)
    gem.save()

    print(f"  [DB] Saved {len(evaluations)} evaluations for {gem_id}")


def perform_search(page: Page, gem_id: str, check_bid_ra_status: bool = False) -> None:
    page.goto("https://bidplus.gem.gov.in/all-bids", wait_until="networkidle")
    page.locator("#searchBid").fill(gem_id, timeout=20000)
    delay(1000)

    search_dropdown = page.locator("button.dropdown-toggle.searchtype")
    if search_dropdown.count() > 0:
        search_dropdown.click()
        delay(500)
        exact_option = page.locator("ul.dropdown-menu a, ul.dropdown-menu li").filter(has_text="Exact").first
        if exact_option.count() > 0:
            exact_option.click()

    delay(1000)
    page.locator("#searchBidRA").click()


    if check_bid_ra_status:
        checkbox = page.locator(
            "label:has-text('BID/RA STATUS') input[type='checkbox']"
        ).first
        if checkbox.count() > 0 and not checkbox.is_checked():
            checkbox.click()
        delay(1000)

    page.locator("#searchBidRA").click()


def wait_for_search_results(page: Page, gem_id: str, timeout: int = 15000) -> bool:
    try:
        page.locator("a.bid_no_hover").filter(has_text=gem_id).wait_for(
            timeout=timeout, state="attached"
        )
        return True
    except PwTimeoutError:
        body_text = page.locator("body").inner_text()
        if "No data found" in body_text:
            return False
        start = time.time() * 1000
        while (time.time() * 1000) - start < timeout:
            if gem_id in page.locator("body").inner_text():
                return True
            delay(1000)
        return False


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


def get_view_bid_results_url(page: Page) -> Optional[str]:
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
        els = page.locator(sel).filter(has_text=patterns)
        count = els.count()
        for i in range(count):
            anchor = els.nth(i).locator("xpath=ancestor::a").first
            if anchor.count() > 0:
                href = anchor.get_attribute("href")
                if href:
                    return href

    view_text = page.locator("*").filter(
        has_text=re.compile(r"VIEW\s+BID\s+RESULTS", re.IGNORECASE)
    )
    count = view_text.count()
    for i in range(count):
        anchor = view_text.nth(i).locator("xpath=ancestor::a").first
        if anchor.count() > 0:
            href = anchor.get_attribute("href")
            if href:
                return href

    any_view = page.locator("*").filter(
        has_text=re.compile(r"\bVIEW\b", re.IGNORECASE)
    )
    count = any_view.count()
    for i in range(min(count, 100)):
        anchor = any_view.nth(i).locator("xpath=ancestor::a").first
        if anchor.count() > 0:
            href = anchor.get_attribute("href")
            if href:
                return href

    return None

def extract_buyer_details(page: Page) -> str:
    import json
    body_text = page.locator("body").inner_text()

    match = re.search(
        r"Buyer Details\s*\n(.*?)(\n2\.\s*Evaluation|\nWEB INFO|\Z)",
        body_text,
        re.IGNORECASE | re.DOTALL,
    )
    if not match:
        print("  extract_buyer_details: not found")
        return "{}"

    buyer = {}
    for line in match.group(1).strip().split("\n"):
        line = line.strip()
        if not line or ":" not in line:
            continue
        key, _, value = line.partition(":")
        buyer[key.strip()] = value.strip()

    print(f"  extract_buyer_details: {json.dumps(buyer, indent=2)}")
    return json.dumps(buyer)


def parse_evaluation_table(page: Page) -> list[dict]:
    table = page.locator("#collapseThree table.table").first
    if table.count() == 0:
        print("  parse_evaluation_table: no table found")
        return []

    rows = table.locator("tr")
    row_count = rows.count()
    if row_count < 2:
        return []

    header_cells = rows.first.locator("th, td").all()
    col_idx: dict[str, int] = {}

    for i, cell in enumerate(header_cells):
        text = (cell.inner_text() or "").strip().lower()
        if any(kw in text for kw in ["s.no", "sno", "sn"]):
            col_idx["sno"] = i
        if any(kw in text for kw in ["seller", "bidder", "vendor"]):
            col_idx["seller"] = i
        if any(kw in text for kw in ["offered", "item"]):
            col_idx["offeredItem"] = i
        if any(kw in text for kw in ["total", "price", "amount"]):
            col_idx["totalPrice"] = i
        if "rank" in text:
            col_idx["rank"] = i
        if "status" in text:
            col_idx["status"] = i

    results = []
    if not col_idx:
        for ri in range(1, row_count):
            cells = rows.nth(ri).locator("td")
            results.append(
                {
                    "sellerName": cells.nth(1).inner_text().strip()
                    if cells.count() > 1
                    else "",
                    "offeredItem": cells.nth(2).inner_text().strip()
                    if cells.count() > 2
                    else None,
                    "totalPrice": cells.nth(3).inner_text().strip()
                    if cells.count() > 3
                    else None,
                    "rank": cells.nth(4).inner_text().strip()
                    if cells.count() > 4
                    else None,
                    "status": cells.nth(5).inner_text().strip()
                    if cells.count() > 5
                    else None,
                }
            )
    else:
        for ri in range(1, row_count):
            cells = rows.nth(ri).locator("td")
            results.append(
                {
                    "sellerName": cells.nth(col_idx.get("seller", 1))
                    .inner_text()
                    .strip()
                    if col_idx.get("seller", 1) < cells.count()
                    else "",
                    "offeredItem": cells.nth(col_idx.get("offeredItem", 2))
                    .inner_text()
                    .strip()
                    if col_idx.get("offeredItem", 2) < cells.count()
                    else None,
                    "totalPrice": cells.nth(col_idx.get("totalPrice", 3))
                    .inner_text()
                    .strip()
                    if col_idx.get("totalPrice", 3) < cells.count()
                    else None,
                    "rank": cells.nth(col_idx.get("rank", 4))
                    .inner_text()
                    .strip()
                    if col_idx.get("rank", 4) < cells.count()
                    else None,
                    "status": cells.nth(col_idx.get("status", 5))
                    .inner_text()
                    .strip()
                    if col_idx.get("status", 5) < cells.count()
                    else None,
                }
            )

    return results


def process_tender(page: Page, gem_id: str, browser) -> dict:
    print(f"Processing {gem_id}")

    for attempt in range(1, 3):
        with_checklist = attempt == 2
        print(
            f"  {gem_id}: searching {'WITH' if with_checklist else 'WITHOUT'} "
            f"Bid/RA Status (attempt {attempt}/2)"
        )

        try:
            perform_search(page, gem_id, with_checklist)

            print(f"  {gem_id}: waiting for search results")
            has_results = wait_for_search_results(page, gem_id)
            if not has_results:
                print(f"  {gem_id}: no data found on attempt {attempt}")
                continue

            delay(2000)

            row_info = find_gem_id_result(page, gem_id)
            if not row_info:
                print(f"  {gem_id}: row not found on attempt {attempt}")
                continue

            print(f'  {gem_id}: bid status — "{row_info.get("bidStatus")}"')

            if not row_info.get("hasViewBidResults"):
                try:
                    body = page.locator("body").inner_text()
                    idx = body.find(gem_id)
                    if idx == -1:
                        page_dump = "GemId text not found in page"
                    else:
                        start = max(0, idx - 200)
                        end = min(len(body), idx + 400)
                        page_dump = body[start:end]
                    print(f"  {gem_id}: page content around gemId — {page_dump}")
                except Exception:
                    pass
                print(
                    f"  {gem_id}: View BID Results button not found "
                    f"on attempt {attempt}, will retry"
                )
                continue

            print(f"  {gem_id}: getting View BID Results URL")
            view_url = get_view_bid_results_url(page)
            if not view_url:
                print(f"  {gem_id}: View BID Results URL not found")
                continue

            full_url = urljoin("https://bidplus.gem.gov.in", view_url)
            print(f"  {gem_id}: opening {full_url}")
            bid_results_page = browser.new_page(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            )
            bid_results_page.goto(full_url, wait_until="domcontentloaded")

            current_url = bid_results_page.url
            print(f"  {gem_id}: current URL after goto — {current_url}")

            if "getSinglePacketResultView" not in current_url:
                print(f"  {gem_id}: WARNING — page redirected to {current_url}, re-navigating...")
                bid_results_page.close()
                bid_results_page = browser.new_page(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
                )
                bid_results_page.goto(full_url, wait_until="networkidle")
                current_url = bid_results_page.url
                print(f"  {gem_id}: URL after re-navigate — {current_url}")

            print(f"  {gem_id}: page title — '{bid_results_page.title()}'")
            try:
                body_preview = bid_results_page.locator("body").inner_text()[:1000]
                # print(f"  {gem_id}: body preview:\n{body_preview}")
            except Exception as e:
                print(f"  {gem_id}: could not read body — {e}")

            print(f"  {gem_id}: extracting buyer details")
            buyer_details = extract_buyer_details(bid_results_page)

            print(f"  {gem_id}: parsing evaluation table")
            evaluations = parse_evaluation_table(bid_results_page)
            # price_diff = calculate_difference(evaluations)

            print(f"  {gem_id}: evaluation complete — {len(evaluations)} rows")
            bid_results_page.close()
            print(f"  {gem_id}: closed bid results page")
            return {
                "id": 0,
                "gemId": gem_id,
                "success": True,
                "bidStatus": row_info.get("bidStatus"),
                "evaluations": evaluations,
                "buyerDetails": buyer_details,
                # "priceDifference": price_diff,
            }

        except Exception as e:
            print(f"  {gem_id}: error on attempt {attempt} — {e}")

    return {
        "id": 0,
        "gemId": gem_id,
        "success": False,
        "error": "All attempts failed",
    }


def extract_bid_results(
    gem_ids: list[str],
    on_progress: Optional[Callable[[int, int], None]] = None,
) -> list[dict]:
    chrome_path = os.environ.get("CHROME_PATH") or detect_chrome_path()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            executable_path=chrome_path,
            headless=settings.HEADLESS_BROWSER,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-features=ChromeWhatsNewUI",
                "--disable-infobars",
                "--no-sandbox",
                "--disable-web-security",
            ],
        )
        page = browser.new_page(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        )

        results = []
        try:
            for i, gem_id in enumerate(gem_ids):
                result = process_tender(page, gem_id, browser)
                result["id"] = i + 1
                results.append(result)
                if on_progress:
                    on_progress(i + 1, len(gem_ids))
        finally:
            browser.close()

    # print(results)
    for result in results:
        _save_to_db(result["gemId"], result)

    return [
        {
            "id": r["id"],
            "gemId": r["gemId"],
            "success": r["success"],
            "bidStatus": r.get("bidStatus"),
            "evaluationCount": len(r.get("evaluations", [])),
            "buyerDetails": r.get("buyerDetails"),
        }
        for r in results
    ]


