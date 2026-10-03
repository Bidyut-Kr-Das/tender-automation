"""Copied from tender_search/services/google_drive.py (_get_authenticated_service); DB code removed."""
import os
import logging
from google.oauth2.credentials import Credentials
from google.oauth2.service_account import Credentials as ServiceAccountCredentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from django.conf import settings
logger = logging.getLogger(__name__)
SCOPES = ["https://www.googleapis.com/auth/drive.file"]


def _get_authenticated_service():
    token_path = settings.GOOGLE_DRIVE_TOKEN_PATH
    creds_path = settings.GOOGLE_DRIVE_CREDENTIALS_PATH
    creds = None

    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)

    if creds and creds.valid:
        return build("drive", "v3", credentials=creds)

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(token_path, "w") as f:
            f.write(creds.to_json())
        return build("drive", "v3", credentials=creds)

    if os.path.exists(creds_path):
        try:
            flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
            creds = flow.run_local_server(port=0)
            token_path.parent.mkdir(parents=True, exist_ok=True)
            with open(token_path, "w") as f:
                f.write(creds.to_json())
            return build("drive", "v3", credentials=creds)
        except Exception as e:
            logger.warning("OAuth flow failed, falling back to service account: %s", e)

    logger.info("Using service account authentication")
    sa_creds = ServiceAccountCredentials.from_service_account_info(
        {
            "client_email": settings.GDRIVE_CLIENT_EMAIL,
            "private_key": settings.GDRIVE_PRIVATE_KEY,
            "token_uri": "https://oauth2.googleapis.com/token",
        },
        scopes=SCOPES,
    )
    return build("drive", "v3", credentials=sa_creds)
