"""Copied from tender_search/services/browser.py (delay, detect_chrome_path); DB code removed."""
import os
import time
from django.conf import settings


def delay(ms: int) -> None:
    time.sleep(ms / 1000)


def detect_chrome_path() -> str:
    # Prefer path provided through environment variable
    chrome_path = settings.CHROME_PATH

    if chrome_path:
        if os.path.exists(chrome_path):
            return chrome_path

        raise FileNotFoundError(
            f"Chrome executable not found at CHROME_PATH: {chrome_path}"
        )

    # Fallback for local Windows development
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files\Chromium\Application\chrome.exe",
    ]

    for p in candidates:
        if os.path.exists(p):
            return p

    raise FileNotFoundError(
        "Chrome not found. Set the CHROME_PATH environment variable."
    )
