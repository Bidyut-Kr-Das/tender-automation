"""sync_result self-check. No browser, no DB, no network: scrapers and emit are stubbed.

Run: uv run python -m automation_v2.test_sync_result
"""
import os
import tempfile
from pathlib import Path

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

import openpyxl  # noqa: E402

from automation_v2 import dispatch, sync_result  # noqa: E402
from automation_v2.lib import result_scrapers as rs  # noqa: E402


def xlsx(rows) -> Path:
    wb = openpyxl.Workbook()
    for r in rows:
        wb.active.append(r)
    path = Path(tempfile.mkdtemp()) / "r.xlsx"
    wb.save(path)
    return path


# read_rows: TenderTiger columns
tiger = rs.read_rows(xlsx([
    ["Actual Tender Number", "L1", "Contract Amount"],
    ["GEM/2026/B/1<br>RA/1", "Laser Power & Infra", "1.5 Cr"],
    [None, "x", "1"],                       # no reference: skipped
]), rs.TIGER_COLUMNS)
assert tiger == [{"referenceNo": "GEM/2026/B/1", "reverseAuction": True, "l1": "Laser Power & Infra",
                  "isLaser": True, "contractAmount": "1.5 Cr", "contractValue": "15000000",
                  "competitors": None, "tenderStage": None, "currentStatus": None}], tiger

# read_rows: Tender247 columns
t247 = rs.read_rows(xlsx([
    ["Tender Reference No", "Winner Bidder", "Contract Value", "Participator Bidders", "Tender Stage"],
    ["64265344B", "Other Ltd", "12,345", "A, B", "AOC"],
]), rs.T247_COLUMNS)
assert t247[0]["contractValue"] == "12345" and t247[0]["currentStatus"] == "AWARDED"
assert t247[0]["competitors"] == "A, B" and not t247[0]["isLaser"] and not t247[0]["reverseAuction"]

try:
    rs.read_rows(xlsx([["Foo"]]), rs.TIGER_COLUMNS)
    raise AssertionError("missing columns should raise")
except ValueError:
    pass

# parse_sources
assert sync_result.parse_sources(None) == ["tiger", "t247"]
assert sync_result.parse_sources("247") == ["t247"]
assert sync_result.parse_sources(["tiger", "both"]) == ["tiger", "t247"]
assert sync_result.parse_sources("junk") == ["tiger", "t247"]

# run: one event per source; a failing source does not stop the next
sent = []
dispatch.emit = lambda cid, event, data: sent.append((cid, event, data))


def boom():
    raise RuntimeError("Tiger login failed")


sync_result.SOURCES = {"tiger": ("TENDER_TIGER_RESULT", boom),
                       "t247": ("TENDER247_RESULT", lambda: {"file": "r.xlsx", "rows": t247})}
sync_result.run("whk_test", ["tiger", "t247"])
assert [e for _, e, _ in sent] == ["result.synced_failed", "result.synced_success"], sent
assert sent[0][2] == {"type": "TENDER_TIGER_RESULT", "result": None, "error": "RuntimeError: Tiger login failed"}
assert sent[1][2]["result"]["rows"] == t247 and sent[1][0] == "whk_test"

print("ok")
