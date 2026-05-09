# UFOWARrip
# Created by Prizmatik
# https://github.com/prizmatik666/UFOWARrip

from core.index_store import load_index, save_index
from core.downloader import existing_valid, media_type_for_record, output_path, sha256_file, state_for


DEFAULT_EXTENSIONS = {
    "pdf": ".pdf",
    "img": ".png",
    "vid": ".mp4",
}


def media_url(rec, media_type):
    if media_type == "pdf":
        return rec.get("url") or ""
    if media_type == "img":
        return (rec.get("image") or {}).get("url") or ""
    if media_type == "vid":
        return (rec.get("video") or {}).get("url") or ""
    return ""


def verify_item(cfg, asset, rec, media_type):
    url = media_url(rec, media_type)
    dl = state_for(rec, media_type)

    if not url:
        dl.update({
            "downloaded": False,
            "status": "missing_no_harvested_url",
            "path": None,
            "bytes": None,
            "sha256": None,
        })
        return "missing_no_url", None

    item = {
        "media_type": media_type,
        "asset": asset,
        "url": url,
        "rec": rec,
        "default_ext": DEFAULT_EXTENSIONS[media_type],
    }
    path = output_path(cfg, item)
    ok, reason = existing_valid(media_type, path)

    if ok:
        dl.update({
            "downloaded": True,
            "path": str(path),
            "status": "verified",
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        })
        dl.pop("error", None)
        dl.pop("failed_at", None)
        return "present", path

    dl.update({
        "downloaded": False,
        "path": str(path),
        "status": "missing" if reason == "missing" else f"invalid:{reason}",
        "bytes": None,
        "sha256": None,
    })
    return "missing", path


def verify_downloads(cfg):
    cfg.ensure_dirs()
    index = load_index(cfg)
    records = index.get("records", {})

    stats = {
        "pdf": {"present": 0, "missing": 0, "missing_no_url": 0},
        "img": {"present": 0, "missing": 0, "missing_no_url": 0},
        "vid": {"present": 0, "missing": 0, "missing_no_url": 0},
        "unknown": 0,
    }

    for asset, rec in sorted(records.items()):
        media_type = media_type_for_record(rec)
        if media_type not in {"pdf", "img", "vid"}:
            stats["unknown"] += 1
            continue

        status, _path = verify_item(cfg, asset, rec, media_type)
        if status == "present":
            stats[media_type]["present"] += 1
        elif status == "missing_no_url":
            stats[media_type]["missing_no_url"] += 1
        else:
            stats[media_type]["missing"] += 1

    save_index(cfg, index)

    present = sum(stats[mt]["present"] for mt in ["pdf", "img", "vid"])
    missing = sum(stats[mt]["missing"] + stats[mt]["missing_no_url"] for mt in ["pdf", "img", "vid"])

    print(f"[✓] Present: {present}")
    print(f"[!] Missing: {missing}")
    print(
        "    PDFs:   "
        f"{stats['pdf']['present']} present | "
        f"{stats['pdf']['missing']} missing | "
        f"{stats['pdf']['missing_no_url']} no URL"
    )
    print(
        "    Images: "
        f"{stats['img']['present']} present | "
        f"{stats['img']['missing']} missing | "
        f"{stats['img']['missing_no_url']} no URL"
    )
    print(
        "    Videos: "
        f"{stats['vid']['present']} present | "
        f"{stats['vid']['missing']} missing | "
        f"{stats['vid']['missing_no_url']} no URL"
    )
    if stats["unknown"]:
        print(f"    Unknown record types skipped: {stats['unknown']}")
