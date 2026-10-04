"""No DB code; used by both automation_v2 and tender_search."""
import boto3
from pathlib import Path
from urllib.parse import quote
from django.conf import settings


def _client():
    # ponytail: global client, per-call client if credential rotation needed
    return boto3.client(
        "s3",
        endpoint_url=settings.S3_ENDPOINT_URL or None,
        aws_access_key_id=settings.S3_ACCESS_KEY or None,
        aws_secret_access_key=settings.S3_SECRET_KEY or None,
        region_name=getattr(settings, "S3_REGION", "us-east-1"),
    )


class FileStorageService:
    # ponytail: flat folder per tender, replace / with _ to avoid nested prefix
    def upload(self, file_path, reference_no=None, key=None, extra_args=None):
        p = Path(file_path)
        fname = key or p.name
        safe_ref = reference_no.replace("/", "_").replace("\\", "_").strip() if reference_no else ""
        k = f"{safe_ref}/{fname}" if safe_ref else fname
        bucket = settings.S3_BUCKET
        _client().upload_file(str(p), bucket, k, ExtraArgs=extra_args or {})
        # ponytail: S3_ENDPOINT_URL for upload, PUBLIC_URL_ENV for public DB URL, stdlib quote encodes / to %2F
        public_base = getattr(settings, "S3_PUBLIC_URL", "") or settings.S3_ENDPOINT_URL
        encoded_key = quote(k, safe="")
        url = f"{public_base.rstrip('/')}/{bucket}/{encoded_key}"
        return {"bucket": bucket, "key": k, "url": url}
file_storage = FileStorageService()
