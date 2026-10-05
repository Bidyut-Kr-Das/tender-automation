# automation-v2 Webhook Events

This guide is for anyone who publishes jobs to the automation-v2 workers or receives their webhooks. It covers:

- the job payloads each queue accepts
- the four webhook events
- the exact body each job type sends, with examples
- how to verify a request

For how the feature is built, see [webhooks-implementation-guide.md](webhooks-implementation-guide.md).

---

## 1. How it works

1. Register an endpoint on the `/webhooks` page (the `automation-v2-api` service, host port 4122). Registration gives you:
   - a **client ID** (`whk_…`)
   - a **secret** (`whsec_…`)
   - the events you turned on
2. Publish a job to an automation-v2 queue and include your `client_id`.
3. When the job ends, **exactly one** event is sent to your endpoint: `_success` or `_failed`.

Notes:

- Workers never publish follow-up jobs. For example, a finished download does not start a parse. Your system decides what to run next, based on the webhook.
- automation-v2 has no tender database. Everything a job needs must be in its payload, and everything it produces comes back in the webhook.

| Worker | Queue (default) | Event base |
|---|---|---|
| `consume_tender_tasks_v2` | `automation-v2:tasks` (`V2_TASKS_QUEUE`) | `file.fetched` |
| `consume_tender_parsing_v2` | `automation-v2:parsing` (`V2_PARSING_QUEUE`) | `file.parsed` |

---

## 2. Job payloads (what you publish)

Every payload is a JSON object. It must include:

- `type`
- `referenceNo`
- `client_id` (or `clientId`)

Without `client_id`, the job still runs, but no webhook is sent. Keys the worker does not recognise are ignored.

### Tasks queue: `automation-v2:tasks`

| `type` | Required fields | Optional (ignored) |
|---|---|---|
| `GEM_DOWNLOAD` | `referenceNo` | `gemId`, `tenderId` |
| `RA_GEM_DOWNLOAD` | `referenceNo` | `tenderId` |
| `NON_GEM_DOWNLOAD` | `referenceNo` | `tenderId` |

```json
{"type": "GEM_DOWNLOAD", "referenceNo": "GEM/2026/B/1234567", "client_id": "whk_3f9a21c0b7e4d5a6"}
```

### Parsing queue: `automation-v2:parsing`

| `type` | Required fields | Optional |
|---|---|---|
| `GEM_PDF_PARSING` | `referenceNo`, `file_link` | – |
| `RA_GEM_PDF_PARSING` | `referenceNo`, `file_link` | – |
| `NON_GEM_BOQ_PARSING` | `referenceNo`, `file_link` | – |
| `COSTING_ATTACHMENT_PARSING` | `referenceNo`, plus **either** `file_link` **or** `file_type: "network"` with `decrypted_fileId` | `sender` (ignored) |

Rules for these fields:

- **`file_link`** can be:
  - an http(s) URL, such as the S3 `url` from a `file.fetched_success` event
  - a Google Drive `/file/d/<id>/` link
- **`GEM_PDF_PARSING`** now **requires** `file_link`. The legacy worker looked the file up in the database; v2 cannot.
- **`decrypted_fileId`** has the form `"<source>|<relative path>"`. `<source>` is one of `network`, `costing` or `conductor`, and it resolves against the matching network-path setting.

```json
{"type": "GEM_PDF_PARSING", "referenceNo": "GEM/2026/B/1234567",
 "file_link": "https://s3.example.com/tenders/GEM_2026_B_1234567%2FGEM-2026-B-1234567_20260930_101500.pdf",
 "client_id": "whk_3f9a21c0b7e4d5a6"}
```

```json
{"type": "COSTING_ATTACHMENT_PARSING", "referenceNo": "GEM/2026/B/1234567",
 "file_type": "network", "decrypted_fileId": "costing|2026/Cable/costing.xlsx",
 "client_id": "whk_3f9a21c0b7e4d5a6"}
```

---

## 3. Events

| Event | Sent when |
|---|---|
| `file.fetched_success` | At least one tender file was downloaded and uploaded to S3. |
| `file.fetched_failed` | The download failed, the payload was invalid, or the job crashed. |
| `file.parsed_success` | The file was downloaded and parsed. |
| `file.parsed_failed` | The download or parse failed, the payload was invalid, or the job crashed. |

These names are fixed. Match on them exactly.

---

## 4. Request format

`POST <your webhook url>`

### Headers

| Header | Example | Meaning |
|---|---|---|
| `Content-Type` | `application/json` | |
| `User-Agent` | `tender-automation-webhooks` | |
| `X-Webhook-Id` | `evt_2c9f0d4e8b1a4f7c9e3d2b1a0f9e8d7c` | Unique per event. De-duplicate on it. |
| `X-Webhook-Event` | `file.parsed_success` | Same as `body.event`. |
| `X-Webhook-Client-Id` | `whk_3f9a21c0b7e4d5a6` | Tells you which secret to use. |
| `X-Webhook-Timestamp` | `1790757600` | Unix seconds at send time. |
| `X-Webhook-Signature` | `sha256=5d1c…` | `hex(HMAC_SHA256(secret, "{timestamp}.{raw_body}"))` |

### Body envelope (same for every event)

```json
{
  "id": "evt_2c9f0d4e8b1a4f7c9e3d2b1a0f9e8d7c",
  "event": "file.fetched_success",
  "created_at": "2026-09-30T10:00:00.123456+00:00",
  "data": {
    "type": "GEM_DOWNLOAD",
    "referenceNo": "GEM/2026/B/1234567",
    "result": {},
    "error": null
  }
}
```

| Field | On `_success` | On `_failed` |
|---|---|---|
| `data.type` | The job `type` from your payload | Same. It is present even if validation failed. |
| `data.referenceNo` | The job `referenceNo` from your payload | Same |
| `data.file_link` | `file.parsed_*` only: the job `file_link` from your payload, or `null` if it had none (e.g. a `network` costing job). Not present on `file.fetched_*`. | Same |
| `data.result` | The result object for that job type (section 5 or 6) | `null` |
| `data.error` | `null` | `"<ErrorType>: <message>"` |

Values that are not JSON-native, such as dates, are sent as strings.

---

## 5. `file.fetched_*`: download jobs

### Result shape

```json
{
  "files": [
    {
      "name": "string: file name",
      "extension": "string: e.g. .pdf, .xlsx",
      "url": "string: public S3 URL (key is %2F-encoded)",
      "key": "string: S3 object key, <reference_no with / -> _>/<file>",
      "tag": "tenderDocument | raDocument | BOQ_FILE",
      "source": "gem | tender247 | tendertiger"
    }
  ],
  "bidStatus": "string | null (RA_GEM_DOWNLOAD only)"
}
```

| Job `type` | `files` | `tag` | `source` | `bidStatus` |
|---|---|---|---|---|
| `GEM_DOWNLOAD` | 1 PDF | `tenderDocument` | `gem` | always `null` |
| `RA_GEM_DOWNLOAD` | 1 PDF | `raDocument` | `gem` | Status text from the GeM listing, or `null` |
| `NON_GEM_DOWNLOAD` | Every file extracted from the downloaded zip | `BOQ_FILE` if the name contains "boq" and the extension is `.xls/.xlsx/.xlsm/.xlsb`; otherwise `tenderDocument` | `tender247`, or `tendertiger` when tender247 failed | always `null` |

### Example: `GEM_DOWNLOAD`, success

```json
{
  "id": "evt_0a1b2c3d4e5f60718293a4b5c6d7e8f9",
  "event": "file.fetched_success",
  "created_at": "2026-09-30T10:15:02.481920+00:00",
  "data": {
    "type": "GEM_DOWNLOAD",
    "referenceNo": "GEM/2026/B/1234567",
    "result": {
      "files": [
        {
          "name": "GEM-2026-B-1234567_20260930_101500.pdf",
          "extension": ".pdf",
          "url": "https://s3.example.com/tenders/GEM_2026_B_1234567%2FGEM-2026-B-1234567_20260930_101500.pdf",
          "key": "GEM_2026_B_1234567/GEM-2026-B-1234567_20260930_101500.pdf",
          "tag": "tenderDocument",
          "source": "gem"
        }
      ],
      "bidStatus": null
    },
    "error": null
  }
}
```

### Example: `RA_GEM_DOWNLOAD`, success

```json
{
  "id": "evt_1b2c3d4e5f60718293a4b5c6d7e8f90a",
  "event": "file.fetched_success",
  "created_at": "2026-09-30T10:20:11.004512+00:00",
  "data": {
    "type": "RA_GEM_DOWNLOAD",
    "referenceNo": "GEM/2026/B/1234567",
    "result": {
      "files": [
        {
          "name": "GEM-2026-B-1234567_RA_20260930_102005.pdf",
          "extension": ".pdf",
          "url": "https://s3.example.com/tenders/GEM_2026_B_1234567%2FGEM-2026-B-1234567_RA_20260930_102005.pdf",
          "key": "GEM_2026_B_1234567/GEM-2026-B-1234567_RA_20260930_102005.pdf",
          "tag": "raDocument",
          "source": "gem"
        }
      ],
      "bidStatus": "Bid Award"
    },
    "error": null
  }
}
```

### Example: `NON_GEM_DOWNLOAD`, success

```json
{
  "id": "evt_2c3d4e5f60718293a4b5c6d7e8f90a1b",
  "event": "file.fetched_success",
  "created_at": "2026-09-30T10:31:45.772003+00:00",
  "data": {
    "type": "NON_GEM_DOWNLOAD",
    "referenceNo": "64265344B",
    "result": {
      "files": [
        {
          "name": "Tender_Document.pdf",
          "extension": ".pdf",
          "url": "https://s3.example.com/tenders/64265344B%2FTender_Document.pdf",
          "key": "64265344B/Tender_Document.pdf",
          "tag": "tenderDocument",
          "source": "tender247"
        },
        {
          "name": "BOQ_Cables.xlsx",
          "extension": ".xlsx",
          "url": "https://s3.example.com/tenders/64265344B%2Fdocs%2FBOQ_Cables.xlsx",
          "key": "64265344B/docs/BOQ_Cables.xlsx",
          "tag": "BOQ_FILE",
          "source": "tender247"
        }
      ],
      "bidStatus": null
    },
    "error": null
  }
}
```

To parse a BOQ next, publish `NON_GEM_BOQ_PARSING` with the BOQ file's `url` as `file_link`.

### Example: failure

```json
{
  "id": "evt_3d4e5f60718293a4b5c6d7e8f90a1b2c",
  "event": "file.fetched_failed",
  "created_at": "2026-09-30T10:40:03.118270+00:00",
  "data": {
    "type": "NON_GEM_DOWNLOAD",
    "referenceNo": "64265344B",
    "result": null,
    "error": "FetchFailed: tender247 and tendertiger both failed: no result"
  }
}
```

Typical `error` values:

- `FetchFailed: Could not download GeM PDF`
- `FetchFailed: Could not download RA PDF (bidStatus='...')`
- `FetchFailed: tender247 and tendertiger both failed: ...`
- `FetchFailed: tender247 returned no files` / `FetchFailed: tendertiger returned no files`
- `ValueError: TENDER247_EMAIL and TENDER247_PASSWORD must be configured`
- `ValidationError: ...` (bad payload, e.g. missing `referenceNo` or unknown `type`)
- S3 or network errors, passed through with their original type and message

---

## 6. `file.parsed_*`: parsing jobs

The shape of `result` depends on `data.type`.

### 6.1 `GEM_PDF_PARSING`

`result` is the full structured content of the GeM bid PDF.

| Field | Type | Notes |
|---|---|---|
| `Total_Quantity` | string \| null | |
| `Item_Category_String` | string \| null | Raw category text |
| `Item_Category_List` | string[] | Categories split into items |
| `EMD_Details` | object | Keys `Advisory Bank` and `EMD Amount`, each present only if found |
| `Dated` | string \| null | `DD-MM-YYYY` |
| `Reverse_Auction_Applicable` | bool | |
| `Empanelled_Inspection_Agency` | string \| null | |
| `Technical_Specifications` | object[] | One per item. Each has one of the three shapes below. |
| `Consignees` | object[] | One per item. Each has `Item_Name` and a `Consignee_Data` list. |

`Technical_Specifications` entry shapes:

- `{"Item_Name", "Type": "Grouped-Key-Value", "Data": {group: {key: value}}}`
- `{"Item_Name", "Type": "Flat-Key-Value", "Data": {key: value}}`
- `{"Item_Name", "Type": "Document Links", "Specification_Document_Link", "BOQ_Document_Link"}`

```json
{
  "id": "evt_4e5f60718293a4b5c6d7e8f90a1b2c3d",
  "event": "file.parsed_success",
  "created_at": "2026-09-30T11:02:19.550871+00:00",
  "data": {
    "type": "GEM_PDF_PARSING",
    "referenceNo": "GEM/2026/B/1234567",
    "file_link": "https://s3.example.com/tenders/GEM_2026_B_1234567%2FGEM-2026-B-1234567_20260930_101500.pdf",
    "result": {
      "Total_Quantity": "150",
      "Item_Category_String": "LT XLPE Cable 3.5C x 300 sqmm, LT XLPE Cable 4C x 16 sqmm",
      "Item_Category_List": ["LT XLPE Cable 3.5C x 300 sqmm", "LT XLPE Cable 4C x 16 sqmm"],
      "EMD_Details": {"Advisory Bank": "State Bank of India", "EMD Amount": "50000"},
      "Dated": "15-09-2026",
      "Reverse_Auction_Applicable": true,
      "Empanelled_Inspection_Agency": "RITES",
      "Technical_Specifications": [
        {
          "Item_Name": "LT XLPE Cable 3.5C x 300 sqmm",
          "Type": "Grouped-Key-Value",
          "Data": {
            "Generic": {"Type of Cable": "Power", "Conductor": "Aluminium"},
            "Electrical": {"Voltage Grade": "1.1 kV"}
          }
        },
        {
          "Item_Name": "LT XLPE Cable 4C x 16 sqmm",
          "Type": "Document Links",
          "Specification_Document_Link": "https://bidplus.gem.gov.in/resources/upload/spec_123.pdf",
          "BOQ_Document_Link": "https://bidplus.gem.gov.in/resources/upload/boq_123.xlsx"
        }
      ],
      "Consignees": [
        {
          "Item_Name": "LT XLPE Cable 3.5C x 300 sqmm",
          "Consignee_Data": [
            {"S_No": "1", "Consignee_Name": "Executive Engineer", "Address": "Kolkata 700001", "Quantity": "100", "Delivery_Days": "30"}
          ]
        }
      ]
    },
    "error": null
  }
}
```

### 6.2 `RA_GEM_PDF_PARSING`

| Field | Type | Notes |
|---|---|---|
| `start_date` | string \| null | RA start, as printed in the PDF, e.g. `20-09-2026 11:00:00` |
| `end_date` | string \| null | RA end |

A date that is missing from the PDF is `null`, and the event is still `_success`.

```json
{
  "id": "evt_5f60718293a4b5c6d7e8f90a1b2c3d4e",
  "event": "file.parsed_success",
  "created_at": "2026-09-30T11:05:40.210334+00:00",
  "data": {
    "type": "RA_GEM_PDF_PARSING",
    "referenceNo": "GEM/2026/B/1234567",
    "file_link": "https://s3.example.com/tenders/GEM_2026_B_1234567%2FGEM-2026-B-1234567_RA_20260930_102005.pdf",
    "result": {"start_date": "20-09-2026 11:00:00", "end_date": "20-09-2026 13:00:00"},
    "error": null
  }
}
```

### 6.3 `NON_GEM_BOQ_PARSING`

| Field | Type | Notes |
|---|---|---|
| `boq_file` | string | File name from the link. For a zip, the name of the BOQ file found inside it. |
| `items[].description` | string | |
| `items[].quantity` | number \| `"no_quantity_available"` | |
| `items[].unit` | string | `""` when there is no unit column or value |

Accepted inputs:

- a `.xlsx`, `.xls` or `.csv` file
- a zip containing a file whose name includes `BOQ`

```json
{
  "id": "evt_60718293a4b5c6d7e8f90a1b2c3d4e5f",
  "event": "file.parsed_success",
  "created_at": "2026-09-30T11:10:12.884120+00:00",
  "data": {
    "type": "NON_GEM_BOQ_PARSING",
    "referenceNo": "64265344B",
    "file_link": "https://s3.example.com/tenders/64265344B%2Fdocs%2FBOQ_Cables.xlsx",
    "result": {
      "boq_file": "BOQ_Cables.xlsx",
      "items": [
        {"description": "LT XLPE Cable 3.5C x 300 sqmm", "quantity": 10.0, "unit": "Km"},
        {"description": "Cable jointing kit", "quantity": "no_quantity_available", "unit": ""}
      ]
    },
    "error": null
  }
}
```

### 6.4 `COSTING_ATTACHMENT_PARSING`

The worker reads every `AUTO CALCULATION SHEET` tab. Each header block in those tabs (`DOCKET NO` + `PROPOSE ERP`) becomes one entry in `tables`.

| Field | Type | Notes |
|---|---|---|
| `tables[].base_date` | string \| null | `YYYY-MM-DD` |
| `tables[].docket_no` | string \| null | |
| `tables[].rows[]` | object[] | `item_code`, `item_name`, `quantity` (number \| null), `total_price` (number \| null, 2 dp), `location`, `cva` (`@`-joined CVA values, or `""`) |
| `tables[].materials` | object | Material name to rate (number), for materials used in the table |
| `tables[].header` | string[] | Header row as found |
| `price` | `"FIRM"` \| `"VARIABLE"` | Price basis. Defaults to `FIRM`. |
| `applicableIndex` | `"IEEMA"` \| `"CACMAI"` \| null | |

In v2 this webhook replaces both legacy outputs: the database save and the `laser_cost` POST. `sender` is ignored.

```json
{
  "id": "evt_718293a4b5c6d7e8f90a1b2c3d4e5f60",
  "event": "file.parsed_success",
  "created_at": "2026-09-30T11:15:57.003991+00:00",
  "data": {
    "type": "COSTING_ATTACHMENT_PARSING",
    "referenceNo": "GEM/2026/B/1234567",
    "file_link": null,
    "result": {
      "tables": [
        {
          "base_date": "2026-09-01",
          "docket_no": "D-1234",
          "rows": [
            {
              "item_code": "ERP10023",
              "item_name": "LT XLPE Cable 3.5C x 300 sqmm",
              "quantity": 10.0,
              "total_price": 1234567.89,
              "location": "Kolkata",
              "cva": "12.5@13.1"
            }
          ],
          "materials": {"Copper": 850.5, "Aluminium": 240.0},
          "header": ["DOCKET NO", "PROPOSE ERP ITEM NAME", "QTY", "TOTAL PRICE"]
        }
      ],
      "price": "VARIABLE",
      "applicableIndex": "IEEMA"
    },
    "error": null
  }
}
```

### Example: parse failure

```json
{
  "id": "evt_8293a4b5c6d7e8f90a1b2c3d4e5f6071",
  "event": "file.parsed_failed",
  "created_at": "2026-09-30T11:20:31.640057+00:00",
  "data": {
    "type": "RA_GEM_PDF_PARSING",
    "referenceNo": "GEM/2026/B/1234567",
    "file_link": "https://s3.example.com/tenders/missing.pdf",
    "result": null,
    "error": "HTTPError: 404 Client Error: Not Found for url: https://s3.example.com/tenders/missing.pdf"
  }
}
```

Typical `error` values:

- `ValidationError: ... file_link Field required` (payload missing `file_link`)
- `ValueError: Unsupported file_link: ...`
- `HTTPError: ...` (download failed)
- `FileNotFoundError: No BOQ file found among extracted files`
- `ValueError: file_link or decrypted_fileId is required`
- `FileNotFoundError: Costing file not found at path: ...`
- `ValueError: AUTO CALCULATION SHEET tab not found`
- `ValueError: No valid table headers found (DOCKET NO + PROPOSE ERP)`

---

## 7. Verifying a request

1. Look up the secret for `X-Webhook-Client-Id`.
2. Reject the request if `X-Webhook-Timestamp` is more than 5 minutes from now.
3. Compute `"sha256=" + hex(HMAC_SHA256(secret, timestamp + "." + raw_body))`. Use the **raw** request bytes, never re-serialized JSON.
4. Compare the result with `X-Webhook-Signature` in constant time.
5. Skip any event whose `X-Webhook-Id` you have already processed.

```python
import hashlib, hmac, json, time

SECRETS = {"whk_3f9a21c0b7e4d5a6": "whsec_…"}
MAX_SKEW_S = 300


def verify(headers: dict, raw: bytes) -> dict | None:
    secret = SECRETS.get(headers.get("X-Webhook-Client-Id", ""))
    ts = headers.get("X-Webhook-Timestamp", "")
    if not secret or not ts.isdigit() or abs(time.time() - int(ts)) > MAX_SKEW_S:
        return None
    expected = "sha256=" + hmac.new(secret.encode(), f"{ts}.".encode() + raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, headers.get("X-Webhook-Signature", "")):
        return None
    return json.loads(raw)
```

```js
// Node.js (Express: use express.raw({ type: "application/json" }) so req.body is a Buffer)
const crypto = require("crypto");

function verify(req, secret) {
  const ts = req.get("X-Webhook-Timestamp");
  if (!/^\d+$/.test(ts) || Math.abs(Date.now() / 1000 - Number(ts)) > 300) return null;
  const expected = "sha256=" + crypto.createHmac("sha256", secret)
    .update(Buffer.concat([Buffer.from(`${ts}.`), req.body])).digest("hex");
  const got = Buffer.from(req.get("X-Webhook-Signature") || "");
  if (got.length !== expected.length || !crypto.timingSafeEqual(got, Buffer.from(expected))) return null;
  return JSON.parse(req.body);
}
```

---

## 8. Delivery rules

- **At-least-once delivery.** The same event can arrive more than once, so de-duplicate on `X-Webhook-Id`.
- **Delivered.** Any `2xx` response counts as delivered. Respond quickly and do heavy work asynchronously.
- **Timeout.** Each attempt has a 10 s timeout.
- **Retried** on network errors, timeouts, `5xx` and `429`. Any other `4xx` means you rejected the event, so it is not retried.
- **Retry schedule.** One immediate attempt, then up to **12 retries, 5 minutes apart** (about 1 hour). After that the event is parked (see below).
- **What a retry sends.** The same body and the same `X-Webhook-Id`, with a fresh `X-Webhook-Timestamp` and signature. The signature uses your *current* secret, so after you rotate the secret, retries verify with the new one.
- **Retries follow your current registration.** If you pause, delete or unsubscribe a webhook while its events are waiting, those retries are skipped.
- **Events are sent only when all of these hold:**
  - the job carried a `client_id`
  - a webhook with that client ID exists
  - that webhook is active
  - it is subscribed to the event
- **Invalid JSON.** A message that is not valid JSON produces no event.

### Retry queues (for operators)

| Queue | Role |
|---|---|
| `automation-v2:webhooks:delay` | Holds a failed event for 5 min (`x-message-ttl`). When the time is up, RabbitMQ moves it to the retry queue. |
| `automation-v2:webhooks:retry` | Consumed by `consume_webhook_retry_v2` (service `automation-v2-webhook-retry`), which sends the event again. |
| `automation-v2:webhooks:dead` | Events that failed every retry, plus malformed retry messages. Nothing consumes this queue. |

A message in these queues looks like this:

```json
{
  "client_id": "whk_3f9a21c0b7e4d5a6",
  "event": "file.parsed_success",
  "id": "evt_…",
  "body": "<exact JSON body that is sent>",
  "attempt": 3,
  "error": "HTTP 503"
}
```

- `attempt` is the number of the retry this message will make.
- `error` is the error from the last failed attempt.

**Replaying parked events.** Move the messages from `automation-v2:webhooks:dead` to `automation-v2:webhooks:retry`, using the RabbitMQ management UI's *Move messages* (shovel) feature. Each replayed event gets one more attempt. If that attempt fails, the event goes straight back to the dead queue.

**If the webhooks DB is unavailable during a retry**, the message goes back to the delay queue without using up an attempt.

**If RabbitMQ is unavailable when the first attempt fails**, the event cannot be queued. It is logged and dropped, and the job is not affected.

---

## 9. Typical flow

```
publish GEM_DOWNLOAD (client_id)          ─▶ file.fetched_success  { files: [ { url, tag: "tenderDocument" } ] }
publish GEM_PDF_PARSING (file_link = url) ─▶ file.parsed_success   { Total_Quantity, EMD_Details, ... }

publish NON_GEM_DOWNLOAD                  ─▶ file.fetched_success  { files: [ ..., { url, tag: "BOQ_FILE" } ] }
publish NON_GEM_BOQ_PARSING (BOQ url)     ─▶ file.parsed_success   { boq_file, items: [...] }

publish RA_GEM_DOWNLOAD                   ─▶ file.fetched_success  { files: [ { url, tag: "raDocument" } ], bidStatus }
publish RA_GEM_PDF_PARSING (file_link)    ─▶ file.parsed_success   { start_date, end_date }
```
