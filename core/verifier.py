# UFOWARrip
# Created by Prizmatik
# https://github.com/prizmatik666/UFOWARrip

from core.index_store import load_index, save_index
<<<<<<< HEAD
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
=======
from core.downloader import (
    build_queue,
    existing_valid,
    media_label,
    output_path,
    sha256_file,
    state_for,
    write_download_exclusion_report,
)
>>>>>>> 0604d09 (Release WarRip v3.2)


def verify_downloads(cfg):
    cfg.ensure_dirs()
    index = load_index(cfg)
    media_types = ["pdf", "img", "vid", "aud"]
    queue, missing_counts, missing_items, skipped_other_counts, excluded_items, duplicate_items = build_queue(index, media_types)
    report_path = write_download_exclusion_report(cfg, excluded_items, duplicate_items)

<<<<<<< HEAD
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
=======
    present = 0
    missing = []
    by_type = {mt: 0 for mt in media_types}
    missing_by_type = {mt: 0 for mt in media_types}

    for item in queue:
        path = output_path(cfg, item)
        st = state_for(item["rec"], item["media_type"])
        ok, reason = existing_valid(item["media_type"], path)

        if ok:
            present += 1
            by_type[item["media_type"]] += 1
            st.update({
                "downloaded": True,
                "path": str(path),
                "status": "verified",
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            })
        else:
            missing.append(item)
            missing_by_type[item["media_type"]] += 1
            st.update({
                "downloaded": False,
                "path": str(path),
                "status": f"missing:{reason}",
            })

    save_index(cfg, index)

    missing_total = len(missing)
    no_url_total = sum(missing_counts.values())

    print("\n=== Verify Downloads ===")
    print(f"Release: {cfg.release}")
    print(f"Index records with harvested URLs checked: {len(queue)}")
    print(f"[✓] Present and valid: {present}")
    print(f"[!] Missing or invalid: {missing_total}")
    print(
        "    Valid by type: "
        f"PDFs {by_type['pdf']} | Images {by_type['img']} | "
        f"Videos {by_type['vid']} | Audio {by_type['aud']}"
    )

    if missing_total:
        print(
            "    Missing by type: "
            f"PDFs {missing_by_type['pdf']} | Images {missing_by_type['img']} | "
            f"Videos {missing_by_type['vid']} | Audio {missing_by_type['aud']}"
        )

    print(f"    Records without harvested URL: {no_url_total}")
    if duplicate_items:
        print(f"    Duplicate final endpoints skipped: {len(duplicate_items)}")
        print(f"    Duplicate report: {report_path}")
    if skipped_other_counts:
        print(f"    Other record types skipped: {sum(skipped_other_counts.values())}")

    if missing_total:
        retry_types = [mt for mt, count in missing_by_type.items() if count]
        retry_labels = ", ".join(media_label(mt) for mt in retry_types)
        print("\n[!] Some harvested files are missing or failed validation.")
        print(f"    Recommended next step: run [6] Download harvested media for: {retry_labels}.")
        print("    Existing valid files will be skipped; missing/invalid files will be retried.")

        sample = missing[:5]
        print("    First missing/invalid items:")
        for item in sample:
            path = output_path(cfg, item)
            status = state_for(item["rec"], item["media_type"]).get("status")
            print(f"      - {media_label(item['media_type'])}: {item['asset']} ({status}) -> {path}")

        if missing_total > len(sample):
            print(f"      ...and {missing_total - len(sample)} more.")
    elif no_url_total:
        print("\n[!] All queued downloads are present, but some records do not have harvested URLs yet.")
        print("    Recommended next step: run the relevant harvest mode, then download again.")
    else:
        print("\n[✓] All harvested downloads for this release are present and valid.")
>>>>>>> 0604d09 (Release WarRip v3.2)
