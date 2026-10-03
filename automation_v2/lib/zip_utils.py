"""Copied from tender_search/services/zip_utils.py (extract_and_upload); DB code removed."""
import shutil
import zipfile
from pathlib import Path
from django.conf import settings
from .file_storage import file_storage


def _extract_all_nested(zip_path: Path, dest_dir: Path, max_depth: int = 5):
    # ponytail: iterative nested zip extract via stdlib zipfile, O(n) scan, depth 5
    dest_dir.mkdir(parents=True, exist_ok=True)
    print(f"[ZipUtils] Extracting {zip_path.name} -> {dest_dir}")
    try:
        with zipfile.ZipFile(zip_path, 'r') as z:
            z.extractall(dest_dir)
    except Exception as e:
        print(f"[ZipUtils] Top-level extract failed: {e}")
        raise
    for depth in range(max_depth):
        nested = list(dest_dir.rglob("*.zip"))
        if not nested:
            break
        print(f"[ZipUtils] Depth {depth}: found {len(nested)} nested zips")
        for nz in nested:
            try:
                with zipfile.ZipFile(nz, 'r') as z:
                    z.extractall(dest_dir)
                nz.unlink()
            except Exception as e:
                print(f"[ZipUtils] Failed nested {nz.name}: {e}")
                try:
                    nz.unlink()
                except Exception:
                    pass


def _collect_valid_files(root: Path) -> list[Path]:
    # ponytail: all non-zip files are valid (includes images pdf xls etc), skip empty
    files = []
    for p in root.rglob("*"):
        if p.is_file() and p.suffix.lower() != ".zip" and p.stat().st_size > 0:
            files.append(p)
    return files


def extract_and_upload(zip_path: str | Path, reference_no: str) -> list[dict]:
    """Extract zip recursively and upload each file individually to S3. Returns s3_list."""
    zip_path = Path(zip_path)
    temp_base = Path(settings.TENDER_PARSING_TEMP_DIR)
    extracted_dir = temp_base / f"{reference_no.replace('/', '_')}_extracted"
    if extracted_dir.exists():
        shutil.rmtree(extracted_dir, ignore_errors=True)
    _extract_all_nested(zip_path, extracted_dir)
    valid_files = _collect_valid_files(extracted_dir)
    print(f"[ZipUtils] Extracted {len(valid_files)} valid files from {zip_path.name}")
    # delete original zip — individual files only
    try:
        zip_path.unlink()
    except Exception:
        pass
    s3_list = []
    for f in valid_files:
        try:
            rel = f.relative_to(extracted_dir).as_posix()
            s3_res = file_storage.upload(str(f), reference_no=reference_no, key=rel)
            s3_list.append(s3_res)
            print(f"[ZipUtils] S3 Uploaded: {s3_res['key']} — {s3_res['url']}")
        except Exception as e:
            print(f"[ZipUtils] S3 upload failed for {f.name}: {e}")
    try:
        shutil.rmtree(extracted_dir, ignore_errors=True)
    except Exception:
        pass
    return s3_list
