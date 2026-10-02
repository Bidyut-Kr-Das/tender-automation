import json
import logging
import os
import re
import time
from pathlib import Path
from pprint import pprint

import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from tender_search.models import TenderMerged, TenderFiles
from tender_search.queue import get_channel
from tender_search.queue_types import TenderParsingMessage, CostingAttachmentParsing, parsing_adapter
from tender_search.services.pdf_parser import parse_and_save_gem_pdf
from tender_search.services.costing_excel_parse import parse_costing_excel
from tender_search.services.boq_parser import process_boq
from tender_search.services.gem_ra_pdf_parser import process_ra_document

logger = logging.getLogger(__name__)

DRIVE_FILE_ID_RE = re.compile(r"/file/d/([^/]+)/")
TEMP_DIR = settings.TENDER_PARSING_TEMP_DIR

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


def callback(ch, method, properties, body):
    try:
        raw = json.loads(body)
        # payload = TenderParsingMessage.model_validate(raw)
        payload= parsing_adapter.validate_python(raw)

        logger.info(
            "[tender:parsing] Received type=%s referenceNo=%s payload=%s",
            payload.type,
            payload.referenceNo,
            body.decode(),
        )
        print(f"[tender:parsing] Received: type={payload.type} referenceNo={payload.referenceNo}")
        if payload.type == "GEM_PDF_PARSING":
            reference_no = payload.referenceNo
            tender = TenderMerged.objects.filter(referenceno=reference_no).first()
            if not tender:
                raise ValueError(f"TenderMerged not found for {reference_no}")
            tf = TenderFiles.objects.filter(
                tendermergedid=tender,
                tags__contains=["tenderDocument"],
            ).first()
            if not tf or not tf.url:
                raise ValueError(f"No tenderDocument URL for {reference_no}")

            safe_name = reference_no.replace("/", "-")
            pdf_path = os.path.join(TEMP_DIR, f"{safe_name}.pdf")

            file_id = _extract_drive_file_id(tf.url)
            if file_id:
                logger.info("Downloading file_id=%s -> %s", file_id, pdf_path)
                _download_from_drive(file_id, pdf_path)
            elif tf.url.startswith("http://") or tf.url.startswith("https://"):
                # ponytail: direct tender-document url (e.g. 192.168.1.190), bypass Drive; add auth if needed
                logger.info("Downloading direct URL -> %s : %s", pdf_path, tf.url)
                _download_from_url(tf.url, pdf_path)
            else:
                raise ValueError(f"Could not extract Drive file ID from URL: {tf.url}")

            try:
                logger.info("Parsing PDF for %s...", reference_no)
                result = parse_and_save_gem_pdf(pdf_path)

                if result.get("db_save", {}).get("success"):
                    logger.info("SUCCESS: %s", reference_no)
                    print(f"[tender:parsing] SUCCESS: {reference_no}")
                else:
                    err = result.get("db_save", {}).get("error", "unknown error")
                    raise RuntimeError(f"DB save failed: {err}")

                ch.basic_ack(delivery_tag=method.delivery_tag)
            except Exception as e:
                logger.error("Parse failed for %s: %s", reference_no, e)
                try:
                    t = TenderMerged.objects.get(referenceno=reference_no)
                    t.parsestatus = "FAILED"
                    t.parseerror = str(e)
                    t.save()
                except Exception:
                    pass
                ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
            finally:
                if os.path.exists(pdf_path):
                    try:
                        os.remove(pdf_path)
                        logger.info("Deleted temp file: %s", pdf_path)
                    except Exception as e:
                        logger.warning("Could not delete %s: %s", pdf_path, e)

                time.sleep(0.5)
        elif payload.type == "COSTING_ATTACHMENT_PARSING":
            if payload.file_type == "network" and payload.decrypted_fileId:
                print("decrypted_fileId....... in if", payload.decrypted_fileId)
                source = _resolve_network_path(payload.decrypted_fileId)
            else:
                source = payload.file_link
            print("linkkkk.......", source)
            excel_parse = parse_costing_excel(gemid=payload.referenceNo, appsheet_link=source, sender=payload.sender)
            if excel_parse.get("error"):
                logger.error("Costing parse failed for %s: %s", payload.referenceNo, excel_parse["error"])
                print(f"[tender:parsing] Costing FAILED: {payload.referenceNo} - {excel_parse['error']}")
            else:
                logger.info("SUCCESS: Costing attachment parsed for %s", payload.referenceNo)
                print( "..........Parsed excel...........",)
                pprint(excel_parse)
                print(f"[tender:parsing] Costing SUCCESS: {payload.referenceNo}")
            ch.basic_ack(delivery_tag=method.delivery_tag)
        elif payload.type == "NON_GEM_BOQ_PARSING":
            print("linkkkk.......",payload.file_link)
            boq_parse= process_boq(reference_no=payload.referenceNo, drive_link=payload.file_link)
            logger.info("SUCCESS: BOQ attachment parsed for %s", payload.referenceNo)
            print( "..........Parsed  BOQ excel...........",)
            print(f"[tender:parsing] BOQSUCCESS: {boq_parse}")
            ch.basic_ack(delivery_tag=method.delivery_tag)
        elif payload.type == "RA_GEM_PDF_PARSING":
            print("RA drive link.......", payload.file_link)
            ra_parse = process_ra_document(reference_no=payload.referenceNo, drive_link=payload.file_link)
            logger.info("RA document parsed for %s", payload.referenceNo)
            print("..........Parsed RA document...........")
            print(f"[tender:parsing] RA SUCCESS: {ra_parse}")
            ch.basic_ack(delivery_tag=method.delivery_tag)


    except Exception as e:
        logger.error("Failed to process message: %s", e)
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)


class Command(BaseCommand):
    help = "Consume messages from the tender:parsing RabbitMQ queue"

    def add_arguments(self, parser):
        parser.add_argument(
            "--temp-dir",
            type=str,
            default=TEMP_DIR,
            help=f"Temporary directory for PDF downloads (default: {TEMP_DIR})",
        )

    def handle(self, *args, **options):
        queue = settings.TENDER_PARSING_QUEUE

        global TEMP_DIR
        TEMP_DIR = options["temp_dir"]

        if not settings.MQ_URL:
            raise CommandError(
                "MQ_URL is not set. Please configure it in your environment."
            )

        os.makedirs(TEMP_DIR, exist_ok=True)

        self.stdout.write(f"Connecting to RabbitMQ, listening on queue: {queue}")
        self.stdout.write(f"Temp directory: {TEMP_DIR}")
        self.stdout.write("Press Ctrl+C to stop")

        conn = None
        channel = None

        try:
            channel = get_channel(queue)
            conn = channel.connection
            channel.basic_qos(prefetch_count=1)
            channel.basic_consume(queue=queue, on_message_callback=callback)

            channel.start_consuming()
        except KeyboardInterrupt:
            self.stdout.write("\nShutting down consumer...")
            if channel:
                try:
                    channel.stop_consuming()
                except Exception:
                    pass
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass
            self.stdout.write("Consumer stopped.")
        except Exception as e:
            raise CommandError(f"Consumer error: {e}")
