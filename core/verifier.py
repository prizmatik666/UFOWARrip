# UFOWARrip
# Created by Prizmatik
# https://github.com/prizmatik666/UFOWARrip

from core.index_store import load_index, save_index
from core.downloader import (
    build_queue,
    existing_valid,
    media_label,
    output_path,
    sha256_file,
    state_for,
    write_download_exclusion_report,
)


def verify_downloads(cfg):
    cfg.ensure_dirs()
    index = load_index(cfg)
    media_types = ["pdf", "img", "vid", "aud"]
    queue, missing_counts, missing_items, skipped_other_counts, excluded_items, duplicate_items = build_queue(index, media_types)
    report_path = write_download_exclusion_report(cfg, excluded_items, duplicate_items)

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
