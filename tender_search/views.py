
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_POST
from rest_framework.decorators import api_view
from rest_framework.response import Response
from .services.gem_bid_results import extract_bid_results
from .services.tender247_result import get_tender247_result
from .services.tender_tiger_result import get_tender_tiger_result
from .services.worker_supervisor import (
    WORKER_COMMANDS,
    clear_logs,
    get_logs,
    start,
    status_all,
    stop,
)


@api_view(["POST"])
def gem_bid_results_view(request):
    gem_ids = request.data.get("gem_ids")
    if not gem_ids or not isinstance(gem_ids, list):
        return Response({"error": "gem_ids list is required"}, status=400)
    results = extract_bid_results(gem_ids)
    return Response(results)


@require_GET
def dashboard_home(request):
    return render(request, "dashboard.html")


@require_GET
def worker_status_view(request):
    return JsonResponse(status_all())


@require_POST
def worker_toggle_view(request, worker, action):
    if worker not in WORKER_COMMANDS:
        return JsonResponse({"error": f"Unknown worker: {worker}"}, status=400)
    if action == "start":
        result = start(worker)
    elif action == "stop":
        result = stop(worker)
    else:
        return JsonResponse({"error": f"Unknown action: {action}"}, status=400)
    if "error" in result:
        return JsonResponse(result, status=500)
    return JsonResponse(result)


@require_GET
def dashboard_logs_view(request):
    worker = request.GET.get("worker") or None
    level = request.GET.get("level") or None
    reference = request.GET.get("reference") or None
    try:
        limit = int(request.GET.get("limit", "200"))
    except ValueError:
        limit = 200
    try:
        after = int(request.GET.get("after", "0"))
    except ValueError:
        after = 0
    items, latest = get_logs(
        worker=worker, level=level, reference=reference, limit=limit, after=after
    )
    return JsonResponse({"logs": items, "after": latest})


@require_POST
def dashboard_clear_logs_view(request):
    clear_logs()
    return JsonResponse({"ok": True})


@api_view(["POST"])
def sync_result_view(request):
    # ponytail: sequential both default — avoids Proactor loop clash
    raw = request.data.get("type")
    if raw is None:
        raw = request.data.get("types")
    if raw is None:
        raw = request.data.get("source")
    types: set[str] = set()
    if raw is None or raw == "" or raw == "both":
        types = {"tiger", "t247"}
    elif isinstance(raw, list):
        for v in raw:
            v = str(v).lower().strip()
            if v in ("tiger", "t247", "247", "tender247"):
                types.add("t247" if v in ("247", "tender247") else v)
            elif v == "both":
                types = {"tiger", "t247"}
                break
    else:
        v = str(raw).lower().strip()
        if v in ("tiger", "t247", "247", "tender247"):
            types.add("t247" if v in ("247", "tender247") else v)
        elif v == "both":
            types = {"tiger", "t247"}
        else:
            types = {"tiger", "t247"}
    if not types:
        types = {"tiger", "t247"}

    result: dict = {}
    if "tiger" in types:
        result["tiger"] = get_tender_tiger_result()
    if "t247" in types:
        result["t247"] = get_tender247_result()
    # single type → unwrap for backward compat, both → combined
    if len(types) == 1:
        sole = next(iter(types))
        return Response(result[sole])
    return Response(result)