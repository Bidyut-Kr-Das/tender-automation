"""Scrape today's tender results from TenderTiger / Tender247 and send the rows as result.synced_* webhooks.

Replaces the legacy /api/v1/sync-result/ route. No DB: the receiver matches rows to its own tenders.
One event per source, so `both` sends two events.
"""
import asyncio
import logging
import os

from django.conf import settings

from .dispatch import job_events
from .lib import result_scrapers as rs

logger = logging.getLogger(__name__)


def _scrape(download, columns, email: str, password: str, name: str) -> dict:
    if not email or not password:
        raise ValueError(f"{name}_EMAIL and {name}_PASSWORD must be configured")
    asyncio.set_event_loop(asyncio.new_event_loop())  # same as fetch_non_gem: fresh loop per Playwright run
    path = download(email, password)
    try:
        return {"file": path.name, "rows": rs.read_rows(path, columns)}
    finally:
        os.remove(path)


def scrape_tiger() -> dict:
    return _scrape(rs.download_tiger_results, rs.TIGER_COLUMNS,
                   settings.TENDER_TIGER_EMAIL, settings.TENDER_TIGER_PASSWORD, "TENDER_TIGER")


def scrape_247() -> dict:
    return _scrape(rs.download_247_results, rs.T247_COLUMNS,
                   settings.TENDER247_EMAIL, settings.TENDER247_PASSWORD, "TENDER247")


SOURCES = {"tiger": ("TENDER_TIGER_RESULT", scrape_tiger), "t247": ("TENDER247_RESULT", scrape_247)}


def parse_sources(raw) -> list[str]:
    """Same tolerant input as the legacy view: tiger / t247 / 247 / tender247 / both, or a list. Default both."""
    alias = {"tiger": "tiger", "t247": "t247", "247": "t247", "tender247": "t247"}
    values = raw if isinstance(raw, list) else [raw]
    picked = {alias.get(str(v).lower().strip()) for v in values} - {None}
    if any(str(v).lower().strip() == "both" for v in values):
        picked = set(SOURCES)
    return [s for s in SOURCES if s in picked] or list(SOURCES)


def run(client_id: str, sources: list[str]) -> None:
    for source in sources:  # sequential, like legacy: two browsers at once clash on the event loop
        type_, scrape = SOURCES[source]
        try:
            with job_events("result.synced", client_id, type=type_) as outcome:
                outcome.succeed(scrape())
        except Exception:
            logger.exception("Result sync failed type=%s", type_)  # already reported as result.synced_failed
