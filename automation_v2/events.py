"""Events a registered webhook can subscribe to.

Receivers match on these exact names, so never rename one. Add new events here;
the API validation and the /webhooks UI both read from this dict.
"""

WEBHOOK_EVENTS: dict[str, str] = {
    "file.fetched_success": "Tender files downloaded and uploaded to S3",
    "file.fetched_failed": "Tender files could not be downloaded",
    "file.parsed_success": "Tender file parsed",
    "file.parsed_failed": "Tender file could not be parsed",
}
