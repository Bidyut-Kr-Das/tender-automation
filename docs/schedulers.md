# Schedulers

This repo has **one** scheduled job: the Kestra flow `scheduler.sync_result`. It calls the legacy API once an hour, and the API pulls tender results from TenderTiger and Tender247 into the `TenderMerged` table.

Nothing else runs on a timer. The v2 workers (`automation-v2-tasks`, `automation-v2-parsing`) only consume RabbitMQ jobs, and `automation-v2-api` has no scheduled calls.

> **Current status: not running.** Since commit `474449f`, both services this job needs are commented out in `docker-compose.yml`: `kestra-automation` (the scheduler) and `api-server` (the route it calls). To turn it back on, see [Turning it back on](#turning-it-back-on).

---

## 1. Summary

| | |
|---|---|
| Flow file | `kestra/flows/main_scheduler.sync_result.yml` |
| Flow id / namespace | `sync_result` / `scheduler` |
| Interval | Every hour, on the hour: cron `0 * * * *` |
| Time zone | UTC, Kestra's default (no `timezone` is set). In IST that is hh:30. |
| Calls | `POST http://automation-api-server:8000/api/v1/sync-result/` |
| Body | `{"type": "both"}` |
| Served by | `api-server` service, `tender_search.views.sync_result_view`, legacy settings (`config.settings`) |
| Writes to | `TenderMerged` in the legacy database (`DATABASE_URL`) |

Kestra loads the flow from `./kestra/flows`, mounted at `/flows` with file watching turned on. Editing the YAML on the server updates the flow without a restart.

---

## 2. The request

```http
POST /api/v1/sync-result/
Content-Type: application/json
Authorization: Bearer <KESTRA_EXTERNAL_API_KEY>
x-api-key: <KESTRA_EXTERNAL_API_KEY>

{"type": "both"}
```

### Body

The view reads the first key that is present, in this order: `type`, then `types`, then `source`.

| Value | Runs |
|---|---|
| `"tiger"` | TenderTiger only |
| `"t247"`, `"247"` or `"tender247"` | Tender247 only |
| `"both"`, empty, missing, or anything not recognised | TenderTiger, then Tender247 |
| a list, e.g. `["tiger", "t247"]` | Each source named in the list |

The two sources run **one after the other**, never in parallel.

### Auth

Kestra sends the key in two headers, but **the route does not check either one**. The REST framework settings use `AllowAny` with no authentication classes (`config/settings.py`). Anyone who can reach port 4120 can trigger a sync.

### Response

The request stays open until both scrapes and all DB updates finish. That can take minutes, because each source logs in to the website in a real browser.

With one source, the body is that source's result. With both, it is `{"tiger": {...}, "t247": {...}}`. Each result looks like this:

```json
{
  "success": true,
  "url": "https://...",
  "tenders_file": "/tmp/.../results.xlsx",
  "headers": ["Actual Tender Number", "L1", "Contract Amount", "..."],
  "updates": [
    {"referenceNo": "GEM/2026/B/1234567", "found": true, "updated": true, "nameOfRank1": "...", "currentStatus": "FINANCIAL EVALUATION", "...": "..."},
    {"referenceNo": "64265344B", "found": false, "skipped": "not_found"}
  ],
  "would_update": 12
}
```

On failure: `{"success": false, "error": "Tiger login failed", "url": "..."}`. The HTTP status is still `200`, so Kestra marks the run as successful even when a source failed. Check the response body or the API logs.

---

## 3. What each source does

| | TenderTiger | Tender247 |
|---|---|---|
| Code | `tender_search/services/tender_tiger_result.py` | `tender_search/services/tender247_result.py` |
| Steps | Logs in, opens the Result tab, downloads the tenders Excel | Logs in, opens Indian Result, filters to today's results, downloads the Excel |
| Reference column | `Actual Tender Number` | `Tender Reference No` |
| L1 column | `L1` | `Winner Bidder` |
| Amount column | `Contract Amount` | `Contract Value` |
| Extra columns | none | `Participator Bidders` (logged only), `Tender Stage` (sets the status) |

The Excel file must contain the reference, L1 and amount columns. If any is missing, the source logs `missing columns` and updates nothing.

### How a row updates `TenderMerged` (`tender_result_updater.update_tender_result`)

1. Split the reference on `<br>`. The first part is the reference number. A non-empty second part means a reverse auction applies.
2. Find the tender: `referenceno` matches exactly (case-insensitive) or, failing that, contains the value; **and** `apm = "YES"` **and** `participated = true`. No match: skip (`not_found`).
3. If `nameofrank1` already equals the new L1, skip (`l1_unchanged`).
4. Otherwise set:
   - `nameofrank1` = L1
   - `valueofrank1` = the amount, converted to a plain number. `"1.5 Cr"` becomes `15000000`.
   - If L1 contains "laser power": `ourrank = "1"` and `ourvalue` = the amount. Otherwise both are cleared.
   - `currentstatus` = the Tender247 stage if there is one. Otherwise it stays `AWARDED` or `CANCELLED` if it already was, and becomes `FINANCIAL EVALUATION` if not.
   - `reverseauctionapplicable = true` when step 1 found a reverse auction.

---

## 4. What it needs

### Services

| Service | Why |
|---|---|
| `kestra-automation` | Runs the schedule. Port 4121 is the Kestra UI. |
| `api-server` | Serves the route. Port 4120. Runs Chromium and Playwright. |
| `infra` Docker network | Both services must be on it so Kestra can reach the API. |

### Environment

| Variable | Where | Needed for |
|---|---|---|
| `KESTRA_EXTERNAL_API_KEY` | `.env` read by compose, passed to Kestra as `SECRET_KESTRA_EXTERNAL_API_KEY` | `{{ secret('KESTRA_EXTERNAL_API_KEY') }}` in the flow. Kestra open-source expects `SECRET_*` values to be **base64-encoded**. |
| `DATABASE_URL` | `.env.production` | The legacy DB holding `TenderMerged` |
| `TENDER_TIGER_EMAIL`, `TENDER_TIGER_PASSWORD` | `.env.production` | TenderTiger login. If missing, that source returns `TENDER_TIGER_EMAIL/PASSWORD not configured`. |
| `TENDER247_EMAIL`, `TENDER247_PASSWORD` | `.env.production` | Tender247 login. If missing, that source returns `TENDER247_EMAIL/PASSWORD not configured`. |
| `CHROME_PATH` | set on `api-server` (`/usr/bin/chromium`) | The browser Playwright launches |
| `HEADLESS_BROWSER` | optional, defaults to `true` | Browser mode |
| `TENDER_PARSING_TEMP_DIR` | optional | Where the result Excel files are downloaded. It must be writable. |

### Data

Only tenders with `apm = "YES"` and `participated = true` are ever updated.

---

## 5. Known issues

- **Hostname.** The flow calls `automation-api-server`, but the compose service is called `api-server`. On the `infra` network the container answers to `api-server`. Unless another container uses the name `automation-api-server`, the call fails to resolve. Confirm on the server, and if needed change the flow URI to `http://api-server:8000/api/v1/sync-result/`.
- **No auth on the route.** See [Auth](#auth).
- **Failures look like successes.** The route always returns `200`. See [Response](#response).
- **Long request.** The call holds the HTTP connection open for the whole scrape. If a run takes longer than Kestra's HTTP timeout, Kestra marks it failed while the API keeps working.

---

## Turning it back on

1. In `docker-compose.yml`, uncomment `api-server` and `kestra-automation`.
2. In `.github/workflows/deploy.yml`, add both services to the `docker compose up` line. The deploy only starts the services named on that line:

   ```
   docker compose up -d --remove-orphans --scale automation-v2-tasks=2 automation-v2-tasks automation-v2-parsing automation-v2-api api-server kestra-automation
   ```
3. Check the hostname issue above.
4. To trigger a run by hand, use **Execute** on `scheduler.sync_result` in the Kestra UI (port 4121), or call the route directly:

   ```bash
   curl -X POST http://<server>:4120/api/v1/sync-result/ -H "Content-Type: application/json" -d '{"type": "tiger"}'
   ```
