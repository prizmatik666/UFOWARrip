# UFOWARrip
# Created by Prizmatik
# https://github.com/prizmatik666/UFOWARrip

import hashlib
import re
import time
from collections import Counter
from pathlib import Path
from urllib.parse import unquote, urlsplit

import requests

from core.browser_session import BrowserSession
from core.index_store import load_index, save_index
from core.logger import log, now_iso


MIN_BYTES = {
    "pdf": 8192,
    "img": 1024,
    "vid": 100 * 1024,
}

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}


def sha256_file(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def safe_slug(value):
    value = unquote(value or "")
    value = re.sub(r"\s+", "_", value.strip())
    value = re.sub(r"[^a-zA-Z0-9_.',()[\\]-]+", "_", value)
    value = value.strip("._")
    return (value or "download")[:140]


def url_extension(url, default_ext):
    path = unquote(urlsplit(url or "").path)
    suffix = Path(path).suffix.lower()
    return suffix if suffix else default_ext


def is_war_gov_url(url):
    host = (urlsplit(url or "").netloc or "").lower()
    return host in {"war.gov", "www.war.gov"}


def state_for(rec, media_type):
    if media_type == "pdf":
        return rec.setdefault("download", {})
    if media_type == "img":
        return rec.setdefault("image", {}).setdefault("download", {})
    if media_type == "vid":
        return rec.setdefault("video", {}).setdefault("download", {})
    raise ValueError(f"unknown media type: {media_type}")


def record_type(rec):
    doc = (rec.get("document_type") or "").strip().upper().strip("[]")

    if not doc:
        for cell in reversed(rec.get("raw_cells") or []):
            value = str(cell).strip().upper().strip("[]")
            if value.startswith("."):
                doc = value
                break

    return doc or "UNKNOWN"


def output_dir(cfg, media_type):
    folder = {"pdf": "pdf", "img": "img", "vid": "vid"}[media_type]
    path = cfg.downloads_dir / folder
    path.mkdir(parents=True, exist_ok=True)
    return path


def output_path(cfg, item):
    ext = url_extension(item["url"], item["default_ext"])
    return output_dir(cfg, item["media_type"]) / f"{safe_slug(item['asset'])}{ext}"


def validate_pdf(data):
    if len(data) < MIN_BYTES["pdf"]:
        return False, f"too_small_{len(data)}_bytes"
    if not data.startswith(b"%PDF"):
        return False, "missing_pdf_magic"
    return True, "ok"


def validate_image(data):
    if len(data) < MIN_BYTES["img"]:
        return False, f"too_small_{len(data)}_bytes"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return True, "ok"
    if data.startswith(b"\xff\xd8\xff"):
        return True, "ok"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return True, "ok"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return True, "ok"
    return False, "missing_image_magic"


def validate_video(data):
    if len(data) < MIN_BYTES["vid"]:
        return False, f"too_small_{len(data)}_bytes"
    if b"ftyp" not in data[:64]:
        return False, "missing_mp4_ftyp"
    if data.lstrip()[:1] == b"<":
        return False, "looks_like_html"
    return True, "ok"


def validate_bytes(media_type, data):
    if media_type == "pdf":
        return validate_pdf(data)
    if media_type == "img":
        return validate_image(data)
    if media_type == "vid":
        return validate_video(data)
    return False, f"unknown_media_type_{media_type}"


def read_prefix(path, size=256 * 1024):
    with path.open("rb") as f:
        return f.read(size)


def existing_valid(media_type, path):
    if not path.exists():
        return False, "missing"
    data = read_prefix(path)
    ok, reason = validate_bytes(media_type, data)
    if not ok:
        return False, reason
    if path.stat().st_size < MIN_BYTES[media_type]:
        return False, f"too_small_{path.stat().st_size}_bytes"
    return True, "ok"


def save_success(item, out, status, attempted_url):
    st = state_for(item["rec"], item["media_type"])
    st.update({
        "downloaded": True,
        "path": str(out),
        "status": status,
        "attempted_url": attempted_url,
        "bytes": out.stat().st_size,
        "sha256": sha256_file(out),
        "downloaded_at": now_iso(),
    })
    st.pop("error", None)
    st.pop("failed_at", None)


def save_failure(item, out, status, attempted_url, error):
    st = state_for(item["rec"], item["media_type"])
    st.update({
        "downloaded": False,
        "path": str(out),
        "status": status,
        "attempted_url": attempted_url,
        "error": str(error),
        "failed_at": now_iso(),
        "bytes": None,
        "sha256": None,
    })


def build_queue(index, media_types):
    queue = []
    missing_counts = {mt: 0 for mt in media_types}
    missing_items = []

    for asset, rec in sorted(index.get("records", {}).items()):
        if "pdf" in media_types:
            url = rec.get("url")
            if (
                url
                and rec.get("url_source") == "clicked_download_button"
                and rec.get("confidence") == "high"
                and urlsplit(url).path.lower().endswith(".pdf")
            ):
                queue.append({
                    "media_type": "pdf",
                    "asset": asset,
                    "url": url,
                    "rec": rec,
                    "default_ext": ".pdf",
                })
            elif "pdf" in missing_counts:
                missing_counts["pdf"] += 1
                missing_items.append({"media_type": "pdf", "asset": asset, "rec": rec, "record_type": record_type(rec)})

        if "img" in media_types:
            image = rec.get("image") or {}
            url = image.get("url")
            if url and url_extension(url, "").lower() in IMAGE_EXTENSIONS:
                queue.append({
                    "media_type": "img",
                    "asset": asset,
                    "url": url,
                    "rec": rec,
                    "default_ext": ".png",
                })
            elif "img" in missing_counts:
                missing_counts["img"] += 1
                missing_items.append({"media_type": "img", "asset": asset, "rec": rec, "record_type": record_type(rec)})

        if "vid" in media_types:
            video = rec.get("video") or {}
            url = video.get("url")
            if url and urlsplit(url).path.lower().endswith(".mp4"):
                queue.append({
                    "media_type": "vid",
                    "asset": asset,
                    "url": url,
                    "rec": rec,
                    "default_ext": ".mp4",
                })
            elif "vid" in missing_counts:
                missing_counts["vid"] += 1
                missing_items.append({"media_type": "vid", "asset": asset, "rec": rec, "record_type": record_type(rec)})

    return queue, missing_counts, missing_items


def mark_missing_harvested_urls(missing_items):
    for item in missing_items:
        st = state_for(item["rec"], item["media_type"])
        st.update({
            "downloaded": False,
            "status": "skipped_no_harvested_url",
            "attempted_url": None,
            "error": "no harvested URL for selected media type",
            "failed_at": now_iso(),
            "bytes": None,
            "sha256": None,
        })


def request_download(item, out, cfg):
    tmp = out.with_suffix(out.suffix + ".part")
    tmp.unlink(missing_ok=True)

    headers = {"User-Agent": cfg.user_agent}
    with requests.get(item["url"], headers=headers, stream=True, timeout=cfg.request_timeout_sec) as response:
        status = response.status_code

        if status in (401, 403, 404):
            return False, f"http_{status}", status

        if status != 200:
            return False, f"http_{status}", status

        with tmp.open("wb") as f:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)

    data = read_prefix(tmp)
    ok, reason = validate_bytes(item["media_type"], data)
    if not ok:
        tmp.unlink(missing_ok=True)
        return False, f"validation_failed:{reason}", status

    tmp.replace(out)
    return True, "downloaded", status


def browser_download(page, item, out):
    tmp = out.with_suffix(out.suffix + ".part")
    tmp.unlink(missing_ok=True)

    try:
        with page.expect_download(timeout=60000) as dl_info:
            clicked = page.evaluate(
                """
                (url) => {
                  const a = document.createElement('a');
                  a.href = url;
                  a.download = '';
                  a.rel = 'noopener';
                  a.style.display = 'none';
                  document.body.appendChild(a);
                  a.click();
                  a.remove();
                  return true;
                }
                """,
                item["url"],
            )
            if not clicked:
                return False, "browser_anchor_click_failed"

        download = dl_info.value
        download.save_as(str(tmp))
    except Exception as e:
        tmp.unlink(missing_ok=True)
        return False, f"browser_download_failed:{e}"

    data = read_prefix(tmp)
    ok, reason = validate_bytes(item["media_type"], data)
    if not ok:
        tmp.unlink(missing_ok=True)
        return False, f"validation_failed:{reason}"

    tmp.replace(out)
    return True, "downloaded_browser"


def browser_status_needs_reset(status):
    low = str(status).lower()
    return (
        "target page, context or browser has been closed" in low
        or "download.save_as: canceled" in low
        or "browser_download_failed:" in low
    )


def media_label(media_type):
    return {"pdf": "PDF", "img": "image", "vid": "video"}[media_type]


def media_plural(media_type):
    return {"pdf": "PDFs", "img": "images", "vid": "videos"}[media_type]


def print_nonqueued_breakdown(missing_items):
    by_type = Counter(item.get("record_type") or "UNKNOWN" for item in missing_items)
    total = len(missing_items)
    print(f"Not queued for selected media type: {total}")
    for rec_type, count in sorted(by_type.items()):
        print(f"  {rec_type} records not selected/without selected harvested URL: {count}")


def download_queue(cfg, index, queue):
    stats = {
        "downloaded": 0,
        "skipped_existing": 0,
        "skipped_missing_url": 0,
        "rejected": 0,
        "failed": 0,
    }
    browser_page = None
    browser_session = None

    def close_browser_session():
        nonlocal browser_page, browser_session
        if browser_session is not None:
            browser_session.close()
        browser_session = None
        browser_page = None

    def get_browser_page():
        nonlocal browser_page, browser_session
        if browser_session is None or browser_page is None or browser_page.is_closed():
            close_browser_session()
            browser_session = BrowserSession(cfg)
            browser_page = browser_session.__enter__()
            browser_page.goto(cfg.start_url, wait_until="domcontentloaded", timeout=90000)
            browser_page.wait_for_timeout(2000)
        return browser_page

    try:
        for i, item in enumerate(queue, start=1):
            out = output_path(cfg, item)
            ok, reason = existing_valid(item["media_type"], out)
            if ok:
                save_success(item, out, "exists_verified", item["url"])
                stats["skipped_existing"] += 1
                print(f"[{i}/{len(queue)}] exists verified {media_label(item['media_type'])}: {out.name}")
                save_index(cfg, index)
                continue

            if out.exists():
                print(f"[{i}/{len(queue)}] existing invalid ({reason}), replacing: {out.name}")
                out.unlink(missing_ok=True)

            print(f"[{i}/{len(queue)}] download {media_label(item['media_type'])}: {out.name}")

            try:
                ok, status, http_status = request_download(item, out, cfg)

                if ok:
                    save_success(item, out, "downloaded_requests_verified", item["url"])
                    stats["downloaded"] += 1
                    print(f"    [✓] saved {out.stat().st_size} bytes")
                    save_index(cfg, index)
                    time.sleep(cfg.download_delay_sec)
                    continue

                if status == "http_404":
                    save_failure(item, out, "failed_http_404", item["url"], "HTTP 404")
                    stats["failed"] += 1
                    print("    [!] HTTP 404")

                elif status in {"http_401", "http_403"} and is_war_gov_url(item["url"]):
                    browser_ok, browser_status = browser_download(get_browser_page(), item, out)
                    if browser_ok:
                        save_success(item, out, "downloaded_browser_verified", item["url"])
                        stats["downloaded"] += 1
                        print(f"    [✓] browser saved {out.stat().st_size} bytes")
                    else:
                        if browser_status_needs_reset(browser_status):
                            close_browser_session()

                        save_failure(item, out, "failed_exception", item["url"], browser_status)
                        stats["failed"] += 1
                        print(f"    [!] browser fallback failed: {browser_status}")

                elif status.startswith("validation_failed:"):
                    save_failure(item, out, "rejected_validation_failed", item["url"], status)
                    stats["rejected"] += 1
                    print(f"    [!] rejected: {status}")

                elif status == "http_403":
                    save_failure(item, out, "failed_http_403", item["url"], "HTTP 403")
                    stats["failed"] += 1
                    print("    [!] HTTP 403")

                else:
                    save_failure(item, out, "failed_exception", item["url"], status)
                    stats["failed"] += 1
                    print(f"    [!] failed: {status}")

            except Exception as e:
                save_failure(item, out, "failed_exception", item["url"], e)
                stats["failed"] += 1
                log(cfg, f"download failed {item['asset']}: {e}")
                print(f"    [!] failed: {e}")

            save_index(cfg, index)
            time.sleep(cfg.download_delay_sec)

    finally:
        close_browser_session()

    return stats


def choose_download_types():
    print("\n=== Download Media ===")
    print("[1] PDFs")
    print("[2] Images")
    print("[3] Videos")
    print("[4] All")
    print("[0] Back")

    choice = input("\nChoose: ").strip()

    if choice == "1":
        return ["pdf"]
    if choice == "2":
        return ["img"]
    if choice == "3":
        return ["vid"]
    if choice == "4":
        return ["pdf", "img", "vid"]
    return []


def download_media_types(cfg, media_types):
    cfg.ensure_dirs()
    index = load_index(cfg)

    if not index.get("records"):
        print("[!] No records in index.")
        return

    queue, missing_counts, missing_items = build_queue(index, media_types)
    type_counts = {mt: sum(1 for item in queue if item["media_type"] == mt) for mt in media_types}

    print("\n=== Download Preview ===")
    print(f"Records queued: {len(queue)}")
    print(f"PDFs:   {type_counts.get('pdf', 0)}")
    print(f"Images: {type_counts.get('img', 0)}")
    print(f"Videos: {type_counts.get('vid', 0)}")
    print_nonqueued_breakdown(missing_items)
    for mt in media_types:
        print(f"{media_label(mt)} folder: {output_dir(cfg, mt)}")

    if not queue:
        print("[!] Nothing to download.")
        return

    proceed = input("\nProceed? [y/N] ").strip().lower()
    if proceed != "y":
        print("[WarRip] Download cancelled.")
        return

    mark_missing_harvested_urls(missing_items)
    save_index(cfg, index)

    stats = download_queue(cfg, index, queue)

    print("\n[✓] Download pass complete.")
    print(f"Downloaded:        {stats['downloaded']}")
    print(f"Skipped existing:  {stats['skipped_existing']}")
    print(f"Not queued for selected media type: {sum(missing_counts.values())}")
    print(f"Rejected:          {stats['rejected']}")
    print(f"Failed:            {stats['failed']}")


def download_missing(cfg):
    media_types = choose_download_types()
    if not media_types:
        return
    download_media_types(cfg, media_types)
