# UFOWARrip
# Created by Prizmatik
# https://github.com/prizmatik666/UFOWARrip

import json
from core.logger import now_iso


def release_name(cfg):
    return getattr(cfg, "release", "release_1")


def index_path(cfg):
    cfg.ensure_dirs()
    return cfg.data_dir / f"index_{release_name(cfg)}.json"


def export_path(cfg, base):
    cfg.ensure_dirs()
    return cfg.data_dir / f"{base}_{release_name(cfg)}.txt"


def load_index(cfg):
    path = index_path(cfg)
    if not path.exists():
        return {"records": {}, "updated_at": None}
    return json.loads(path.read_text(encoding="utf-8"))


def save_index(cfg, index):
    index["updated_at"] = now_iso()
    index_path(cfg).write_text(json.dumps(index, indent=2, sort_keys=True), encoding="utf-8")


def merge_record(index, record):
    records = index.setdefault("records", {})
    asset = record["asset_name"]

    old = records.get(asset, {})
    first_seen = old.get("first_seen") or now_iso()

    records[asset] = {
        **old,
        **record,
        "first_seen": first_seen,
        "last_seen": now_iso(),
        "download": old.get("download") or {
            "downloaded": False,
            "path": None,
            "status": None,
            "sha256": None,
            "bytes": None,
            "downloaded_at": None,
        },
    }


def export_candidate_urls(cfg, index):
    urls = [
        rec["url"]
        for rec in sorted(index.get("records", {}).values(), key=lambda r: r.get("asset_name", ""))
        if rec.get("url")
    ]
    path = export_path(cfg, "candidate_urls")
    path.write_text("\n".join(urls) + ("\n" if urls else ""), encoding="utf-8")
    print(f"[✓] Exported {len(urls)} candidate URLs to {path}")


def harvested_url_entries(index, media_types):
    entries = []
    seen = set()

    def add_entry(media_type, asset, url):
        key = url
        if key in seen:
            return
        seen.add(key)
        entries.append({"type": media_type, "asset": asset, "url": url})

    for rec in sorted(index.get("records", {}).values(), key=lambda r: r.get("asset_name", "")):
        asset = rec.get("asset_name", "")

        if "pdf" in media_types:
            url = rec.get("url")
            if (
                url
                and rec.get("url_source") == "clicked_download_button"
                and rec.get("confidence") == "high"
                and url.lower().split("?", 1)[0].endswith(".pdf")
            ):
                add_entry("pdf", asset, url)

        if "img" in media_types:
            url = (rec.get("image") or {}).get("url")
            if url:
                add_entry("img", asset, url)

        if "vid" in media_types:
            url = (rec.get("video") or {}).get("url")
            if url:
                add_entry("vid", asset, url)

        if "aud" in media_types:
            url = (rec.get("audio") or {}).get("url")
            if url:
                add_entry("aud", asset, url)

    return entries


def export_harvested_urls(cfg, index, media_types, numbered=False):
    entries = harvested_url_entries(index, media_types)
    urls = [entry["url"] for entry in entries]

    if media_types == ["pdf"]:
        base = "harvested_pdf_urls"
    elif media_types == ["img"]:
        base = "harvested_image_urls"
    elif media_types == ["vid"]:
        base = "harvested_video_urls"
    elif media_types == ["aud"]:
        base = "harvested_audio_urls"
    else:
        base = "harvested_all_urls"

    if numbered:
        base = f"{base}_numbered"
        lines = [f"{i}) {url}" for i, url in enumerate(urls, start=1)]
    else:
        lines = urls

    path = export_path(cfg, base)
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")

    counts = {
        "pdf": sum(1 for entry in entries if entry["type"] == "pdf"),
        "img": sum(1 for entry in entries if entry["type"] == "img"),
        "vid": sum(1 for entry in entries if entry["type"] == "vid"),
        "aud": sum(1 for entry in entries if entry["type"] == "aud"),
    }

    print(f"[✓] Exported {len(entries)} URLs to {path}")
    print(
        f"    PDFs: {counts['pdf']} | Images: {counts['img']} | "
        f"Videos: {counts['vid']} | Audio: {counts['aud']}"
    )


def summarize_index(cfg):
    index = load_index(cfg)
    records = index.get("records", {})
    downloaded = sum(1 for r in records.values() if r.get("download", {}).get("downloaded"))
    failed = sum(1 for r in records.values() if "failed" in str(r.get("download", {}).get("status", "")))

    print("\n=== Index Summary ===")
    print(f"Records:     {len(records)}")
    print(f"Downloaded:  {downloaded}")
    print(f"Failed:      {failed}")
    print(f"Index path:  {index_path(cfg)}")
    print(f"Updated at:  {index.get('updated_at')}")
