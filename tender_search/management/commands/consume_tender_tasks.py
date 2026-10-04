import json
import logging
import uuid
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from tender_search.queue import get_channel, publish
from tender_search.queue_types import (
    GemDownloadTask,
    NonGemDownloadTask,
    RAGemDownloadTask,
    tender_tasks_adapter,
)
from automation_v2.lib.non_gem_tender_pdf_downloader import login_tender247
from automation_v2.lib.tender_tiger import login_tiger
from tender_search.models import TenderMerged, TenderFiles
from tender_search.services.gem_pdf_downloader import download_gem_pdf
from tender_search.services.gem_ra_pdf_downloader import download_ra_pdf
from tender_search.constants import TENDER_FILE_TYPES
logger = logging.getLogger(__name__)
import asyncio


def _publish_ingestion(ch, reference_no: str, files: list[dict]):
    # ponytail: fire-and-forget, best-effort; upgrade to retry/nack if ingestion becomes critical
    try:
        job_id = str(uuid.uuid4())
        publish(ch, settings.AGENT_INGESTION_QUEUE, {"job_id": job_id, "referenceNo": reference_no, "files": files})
        logger.info("Published agent:ingestion for %s job_id=%s files=%d", reference_no, job_id, len(files))
        print(f"[agent:ingestion] Published for {reference_no} job_id={job_id} files={len(files)}")
    except Exception as e:
        logger.warning("agent:ingestion publish failed for %s: %s", reference_no, e)


if hasattr(asyncio, "WindowsProactorEventLoopPolicy"):
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())


def callback(ch, method, properties, body):
    try:
        raw = json.loads(body)
        payload = tender_tasks_adapter.validate_python(raw)
        logger.info(
            "[tender:tasks] Received type=%s payload=%s",
            payload.type,
            body.decode(),
        )
        print(f"[tender:tasks] Received: type={payload.type} payload={raw}")

        if isinstance(payload, GemDownloadTask):
            gem_result = download_gem_pdf(payload.referenceNo)
            print("GEM_RESULT.....................", gem_result)

            if gem_result.get("success"):
                publish(ch, settings.TENDER_PARSING_QUEUE, {"type": "GEM_PDF_PARSING", "referenceNo": payload.referenceNo})
                logger.info("Published GEM parsing job for %s", payload.referenceNo)
                link = gem_result.get("s3Link") or gem_result.get("driveLink") or ""
                if link:
                    pdf_path = gem_result.get("pdfPath") or ""
                    filename = Path(pdf_path).name if pdf_path else link.split("/")[-1].split("?")[0] or f"{payload.referenceNo}.pdf"
                    tf = TenderFiles.objects.filter(url=link).order_by("-id").first()
                    if not tf:
                        logger.warning("Skip agent:ingestion for %s — TenderFiles not found for %s", payload.referenceNo, link)
                    else:
                        file_tag = tf.tags[0] if tf.tags else TENDER_FILE_TYPES["TENDER_DOCUMENT"]
                        _publish_ingestion(ch, payload.referenceNo, [{"fileName": filename, "fileUrl": link, "fileTag": file_tag, "externalDocumentId": tf.id}])
            else:
                logger.error("GEM_DOWNLOAD failed for %s: %s", payload.gemId, gem_result.get("error"))

            ch.basic_ack(delivery_tag=method.delivery_tag)
        elif isinstance(payload, RAGemDownloadTask):
            ra_result = download_ra_pdf(payload.referenceNo)
            print("RA_RESULT.....................", ra_result)

            if ra_result.get("success"):
                # ponytail: prefer S3 URL (public bucket), fallback to Drive
                s3_link = ra_result.get("s3Link") or ra_result.get("driveLink", "")
                publish(ch, settings.TENDER_PARSING_QUEUE, {"type": "RA_GEM_PDF_PARSING", "referenceNo": payload.referenceNo, "file_link": s3_link})
                logger.info("Published RA GEM parsing job for %s", payload.referenceNo)
                if s3_link:
                    pdf_path = ra_result.get("pdfPath") or ""
                    filename = Path(pdf_path).name if pdf_path else s3_link.split("/")[-1].split("?")[0] or f"{payload.referenceNo}.pdf"
                    tf = TenderFiles.objects.filter(url=s3_link).order_by("-id").first()
                    if not tf:
                        logger.warning("Skip agent:ingestion for %s — TenderFiles not found for %s", payload.referenceNo, s3_link)
                    else:
                        file_tag = tf.tags[0] if tf.tags else "raDocument"
                        _publish_ingestion(ch, payload.referenceNo, [{"fileName": filename, "fileUrl": s3_link, "fileTag": file_tag, "externalDocumentId": tf.id}])
            else:
                logger.error("RA_GEM_DOWNLOAD failed for %s: %s", payload.referenceNo, ra_result.get("error"))

            ch.basic_ack(delivery_tag=method.delivery_tag)
        elif isinstance(payload, NonGemDownloadTask):
            reference_no = payload.referenceNo or payload.tenderId
            email = settings.TENDER247_EMAIL
            password = settings.TENDER247_PASSWORD
            if not email or not password:
                raise ValueError("TENDER247_EMAIL and TENDER247_PASSWORD must be configured")

            asyncio.set_event_loop(asyncio.new_event_loop())
            result = login_tender247(email, password, reference_no)

            if result.get("success"):
                # ponytail: per-file S3 via zip_utils, s3_list contains individual docs
                s3_list = result.get("s3_list") or []
                if not s3_list:
                    logger.warning("Tender247 success but no files for %s", reference_no)
                tender_merged = TenderMerged.objects.filter(referenceno=reference_no).first()
                print(f"[Tender247] tender_merged={'found' if tender_merged else 'NOT FOUND'} for {reference_no}, s3_list={len(s3_list)}")
                logger.info("TenderMerged %s for %s", 'found' if tender_merged else 'NOT FOUND', reference_no)
                _ingestion_files = []
                if tender_merged:
                    for s3 in s3_list:
                        if not s3 or not s3.get("url"):
                            continue
                        file_url = s3.get("url", "")
                        file_name = (s3.get("key") or "").split("/")[-1]
                        extension = Path(file_name).suffix if file_name else ""
                        # ponytail: BOQ excel → BOQ_FILE else tenderDocument — via constants
                        is_boq_excel = "boq" in file_name.lower() and extension.lower() in (".xls", ".xlsx", ".xlsm", ".xlsb")
                        print(f"[Tender247] file={file_name} ext={extension} is_boq_excel={is_boq_excel}")
                        tags = [TENDER_FILE_TYPES["BOQ_FILE"]] if is_boq_excel else [TENDER_FILE_TYPES["TENDER_DOCUMENT"]]
                        obj = TenderFiles.objects.create(
                            name=file_name,
                            extension=extension,
                            url=file_url,
                            source="tender247",
                            tags=tags,
                            tendermergedid=tender_merged,
                            createdat=timezone.now(),
                            updatedat=timezone.now(),
                        )
                        _ingestion_files.append({"fileName": file_name, "fileUrl": file_url, "fileTag": tags[0], "externalDocumentId": obj.id})
                        if is_boq_excel:
                            print(f"[Tender247] Publishing BOQ file {file_name} to {settings.TENDER_PARSING_QUEUE}")
                            publish(ch, settings.TENDER_PARSING_QUEUE, {"type": "NON_GEM_BOQ_PARSING", "referenceNo": reference_no, "file_link": file_url})
                            logger.info("Published NON_GEM_BOQ_PARSING for %s file %s", reference_no, file_name)
                        else:
                            logger.info("Skipped BOQ parsing for non-BOQ file %s", file_name)
                    if _ingestion_files:
                        _publish_ingestion(ch, str(reference_no), _ingestion_files)
                    else:
                        logger.warning("Skip agent:ingestion for %s — no TenderFiles created", reference_no)
                else:
                    logger.warning("TenderMerged NOT FOUND for %s — skipping TenderFiles + publish", reference_no)
                    print(f"[Tender247] TenderMerged NOT FOUND for {reference_no} — skipping publish")
                logger.info(f"[NON_GEM_DOWNLOAD] Result for {reference_no}: files={len(s3_list)} success={result.get('success')}")
            else:
                tiger_email = settings.TENDER_TIGER_EMAIL
                tiger_password = settings.TENDER_TIGER_PASSWORD
                tiger_result = login_tiger(tiger_email, tiger_password, reference_no)
                if tiger_result.get("success"):
                                # ponytail: recursive zip extract — s3_list contains individual files, no zip
                                s3_list = tiger_result.get("s3_list") or []
                                if not s3_list:
                                    logger.warning("Tiger success but no files extracted for %s", reference_no)
                                tender_merged = TenderMerged.objects.filter(referenceno=reference_no).first()
                                print(f"[Tiger] tender_merged={'found' if tender_merged else 'NOT FOUND'} for {reference_no}, s3_list={len(s3_list)}")
                                logger.info("TenderMerged %s for %s", 'found' if tender_merged else 'NOT FOUND', reference_no)
                                _ingestion_files = []
                                if tender_merged:
                                    for s3 in s3_list:
                                        if not s3 or not s3.get("url"):
                                            continue
                                        file_url = s3.get("url", "")
                                        file_name = (s3.get("key") or "").split("/")[-1]
                                        extension = Path(file_name).suffix if file_name else ""
                                        # ponytail: BOQ excel → BOQ_FILE else tenderDocument — via constants
                                        is_boq_excel = "boq" in file_name.lower() and extension.lower() in (".xls", ".xlsx", ".xlsm", ".xlsb")
                                        print(f"[Tiger] file={file_name} ext={extension} is_boq_excel={is_boq_excel}")
                                        tags = [TENDER_FILE_TYPES["BOQ_FILE"]] if is_boq_excel else [TENDER_FILE_TYPES["TENDER_DOCUMENT"]]
                                        obj = TenderFiles.objects.create(
                                            name=file_name,
                                            extension=extension,
                                            url=file_url,
                                            source="tendertiger",
                                            tags=tags,
                                            tendermergedid=tender_merged,
                                            createdat=timezone.now(),
                                            updatedat=timezone.now(),
                                        )
                                        _ingestion_files.append({"fileName": file_name, "fileUrl": file_url, "fileTag": tags[0], "externalDocumentId": obj.id})
                                        if is_boq_excel:
                                            print(f"[Tiger] Publishing BOQ file {file_name} to {settings.TENDER_PARSING_QUEUE}")
                                            publish(ch, settings.TENDER_PARSING_QUEUE, {"type": "NON_GEM_BOQ_PARSING", "referenceNo": reference_no, "file_link": file_url})
                                            logger.info("Published NON_GEM_BOQ_PARSING for %s file %s", reference_no, file_name)
                                        else:
                                            logger.info("Skipped BOQ parsing for non-BOQ file %s", file_name)
                                    if _ingestion_files:
                                        _publish_ingestion(ch, str(reference_no), _ingestion_files)
                                    else:
                                        logger.warning("Skip agent:ingestion for %s — no TenderFiles created", reference_no)
                                else:
                                    logger.warning("TenderMerged NOT FOUND for %s — skipping TenderFiles + publish", reference_no)
                                    print(f"[Tiger] TenderMerged NOT FOUND for {reference_no} — skipping publish")
                                logger.info(f"[NON_GEM_DOWNLOAD] Tiger success for {reference_no}: files={len(s3_list)} success={tiger_result.get('success')}")
            ch.basic_ack(delivery_tag=method.delivery_tag)
        else:
            logger.warning("Unknown message type: %s", payload.type)
            ch.basic_ack(delivery_tag=method.delivery_tag)
    except Exception as e:
        logger.exception("Failed to process message: %s", e)
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)


class Command(BaseCommand):
    help = "Consume messages from the tender:tasks RabbitMQ queue"

    def handle(self, *args, **options):
        queue = settings.TENDER_TASKS_QUEUE

        if not settings.MQ_URL:
            raise CommandError(
                "MQ_URL is not set. Please configure it in your environment."
            )

        self.stdout.write(f"Connecting to RabbitMQ, listening on queue: {queue}")
        self.stdout.write("Press Ctrl+C to stop")

        conn = None
        channel = None

        try:
            channel = get_channel(queue)
            conn = channel.connection
            ensure = get_channel(settings.TENDER_PARSING_QUEUE)
            ensure.connection.close()
            ensure2 = get_channel(settings.AGENT_INGESTION_QUEUE)
            ensure2.connection.close()
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