"""No DB code; used by both automation_v2 and tender_search."""
import os
import re
import requests
from django.conf import settings
DRIVE_FILE_ID_RE = re.compile(r"/file/d/([^/]+)/")
FILE_SOURCE_BASE_PATH_ENV = {
    "network": "INDEXER_NETWORK_PATH",
    "costing": "COSTING_FILE_NETWORK_PATH",
    "conductor": "CONDUTOR_PATH",
}


def _resolve_network_path(decrypted_file_id: str) -> str:
    print("decrypted_file_id.......", decrypted_file_id )
    if "|" not in decrypted_file_id:
        return decrypted_file_id
    source_key, relative_path = decrypted_file_id.split("|", 1)
    print("source_key.......", source_key)
    print("relative_path.......", relative_path)
    env_var = FILE_SOURCE_BASE_PATH_ENV.get(source_key)
    print("env_var.......", env_var)
    if not env_var:
        raise ValueError(f"Unknown file source key: {source_key}")
    base_path = getattr(settings, env_var, "")
    print("base_path.......", base_path)
    if not base_path:
        raise ValueError(f"Environment variable {env_var} is not set")
    return os.path.join(base_path, relative_path)


def _extract_drive_file_id(url: str) -> str | None:
    m = DRIVE_FILE_ID_RE.search(url)
    return m.group(1) if m else None


def _download_from_drive(file_id: str, dest_path: str) -> bool:
    url = f"https://drive.google.com/uc?export=download&id={file_id}"
    session = requests.Session()

    response = session.get(url, stream=True)
    response.raise_for_status()

    content_type = response.headers.get("Content-Type", "")
    if "text/html" in content_type:
        first_chunk = response.iter_content(chunk_size=32768).__next__()
        text = first_chunk.decode("utf-8", errors="replace")
        m = re.search(r"confirm=([0-9A-Za-z\-_]+)", text)
        if m:
            confirm_token = m.group(1)
            url = f"https://drive.google.com/uc?export=download&confirm={confirm_token}&id={file_id}"
            response = session.get(url, stream=True)
            response.raise_for_status()
        else:
            response = session.get(url, stream=True)
            response.raise_for_status()

    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    with open(dest_path, "wb") as f:
        for chunk in response.iter_content(chunk_size=8192):
            if chunk:
                f.write(chunk)

    return True


def _download_from_url(url: str, dest_path: str) -> bool:
    # ponytail: direct http download for 192.168 tender-document urls; no auth/retry, add if needed
    session = requests.Session()
    response = session.get(url, stream=True, timeout=60)
    response.raise_for_status()
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    with open(dest_path, "wb") as f:
        for chunk in response.iter_content(chunk_size=8192):
            if chunk:
                f.write(chunk)
    return True
