#!/usr/bin/env python3
#
# UFOWARrip reconciliation/audit tool.
# This script is intentionally separate from warrip.py so the main program
# workflow and index-building behavior stay unchanged.

import argparse
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from core.browser_session import BrowserSession
from core.config import Config
from core.release_page import goto_release_page, validate_release_scope


REPORT_NAME = "reconciliation_report.json"
MISSING_NAME = "missing_records.txt"
AARO_INDEX_NAME = "aaro_index.json"


def clean_text(value):
    return re.sub(r"\s+", " ", str(value or "").replace("\ufeff", "")).strip()


def normalize_title(value):
    value = clean_text(value)
    value = value.replace("[", " ").replace("]", " ")
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def normalize_type(value):
    value = clean_text(value).strip("[]").upper()
    if not value:
        return ".PDF"
    return value if value.startswith(".") else f".{value}"


def media_family(record_type):
    record_type = normalize_type(record_type)
    if record_type in {".AUD", ".AUDIO"}:
        return "audio"
    if record_type in {".VID", ".VIDEO", ".MP4", ".MOV", ".WEBM", ".OGG"}:
        return "videos"
    if record_type in {".IMG", ".IMAGE", ".JPG", ".JPEG", ".PNG", ".GIF", ".WEBP"}:
        return "images"
    if record_type == ".PDF":
        return "pdfs"
    return "other"


def record_key(title, record_type):
    return f"{normalize_title(title)}|{normalize_type(record_type)}"


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def release_number_from_index_path(index_path):
    match = re.search(r"index_release_(\d+)\.json$", Path(index_path).name)
    return int(match.group(1)) if match else None


def is_aaro_index_path(index_path):
    return Path(index_path).name == AARO_INDEX_NAME


def discover_index_files(cfg, include_aaro=True):
    cfg.ensure_dirs()
    indexes = sorted(
        cfg.data_dir.glob("index_release_*.json"),
        key=lambda p: (release_number_from_index_path(p) or 0, p.name),
    )
    aaro_path = cfg.data_dir / AARO_INDEX_NAME
    if include_aaro and aaro_path.exists():
        indexes.append(aaro_path)
    return indexes


def describe_index(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if is_aaro_index_path(path):
            items = data.get("items") or {}
            return f"{len(items)} AARO items | updated_at={data.get('updated_at')}"
        records = data.get("records") or {}
        return f"{len(records)} WAR records | updated_at={data.get('updated_at')}"
    except Exception as e:
        return f"unreadable: {e}"


def select_index_file(cfg):
    indexes = discover_index_files(cfg)

    if not indexes:
        raise FileNotFoundError(f"No index_release_*.json or {AARO_INDEX_NAME} files found under {cfg.data_dir}")

    print("\n=== Select Index To Reconcile ===")
    for i, path in enumerate(indexes, start=1):
        release_num = release_number_from_index_path(path)
        if is_aaro_index_path(path):
            release_label = "aaro"
        else:
            release_label = f"release_{release_num}" if release_num else "unknown release"
        print(f"[{i}] {release_label}: {path}")
        print(f"    {describe_index(path)}")
    print("[0] Exit")

    while True:
        choice = input("\nChoose index: ").strip()
        if choice == "0":
            raise SystemExit(0)
        if choice.isdigit() and 1 <= int(choice) <= len(indexes):
            return indexes[int(choice) - 1]
        print("[!] Invalid choice.")


def apply_release_from_index(cfg, index_path):
    release_num = release_number_from_index_path(index_path)
    if release_num and hasattr(cfg, "set_release"):
        cfg.set_release(release_num, save=False)
    return release_num


def extract_rendered_rows(page, page_number):
    return page.evaluate(
        """
        (pageNumber) => {
          const rendered = (el) => {
            const r = el.getBoundingClientRect();
            const s = window.getComputedStyle(el);
            return r.width > 20 &&
                   r.height > 5 &&
                   s.display !== 'none' &&
                   s.visibility !== 'hidden' &&
                   s.opacity !== '0' &&
                   !el.hidden;
          };

          const rows = [...document.querySelectorAll(
            '#recordList .record-row, .record-list .record-row, [data-record-trigger]'
          )].filter(rendered);

          return rows.map((el, index) => {
            const cells = [...el.querySelectorAll('.record-title, .record-meta')]
              .map((node) => (node.textContent || node.innerText || '').trim())
              .filter(Boolean);
            const fallback = (el.innerText || '')
              .split('\\n')
              .map((part) => part.trim())
              .filter(Boolean);
            const values = cells.length ? cells : fallback;
            const titleEl = el.querySelector('.record-title');
            const title = titleEl
              ? (titleEl.textContent || titleEl.innerText || '').trim()
              : (values[0] || '');
            const typeCell = [...values].reverse()
              .find((value) => /^\\[?\\.[a-z0-9]+\\]?$/i.test(value || '')) || '';
            const rowType = typeCell.replace(/[\\[\\]]/g, '').toUpperCase();

            return {
              title,
              type: rowType,
              page: pageNumber,
              row_index: index + 1,
              record_id: el.getAttribute('data-record-id') || '',
              cells: values,
              text: (el.innerText || '').trim()
            };
          }).filter((row) => row.title);
        }
        """,
        page_number,
    )


def extract_site_count_label(page):
    try:
        value = page.evaluate(
            """
            () => {
              const el = document.querySelector('#recordCount');
              return el ? (el.textContent || el.innerText || '').trim() : '';
            }
            """
        )
        return int(value) if str(value).isdigit() else None
    except Exception:
        return None


def active_page_number(page):
    try:
        value = page.evaluate(
            """
            () => {
              const active = document.querySelector('.pagination-button.is-active');
              return active ? (active.textContent || active.innerText || '').trim() : '';
            }
            """
        )
        return int(value) if str(value).isdigit() else None
    except Exception:
        return None


def wait_for_rows(page, cfg):
    for _ in range(40):
        count = page.evaluate(
            """
            () => document.querySelectorAll(
              '#recordList .record-row, .record-list .record-row, [data-record-trigger]'
            ).length
            """
        )
        if count:
            return True
        page.wait_for_timeout(max(250, int(cfg.stable_wait_ms / 2)))
    return False


def scroll_to_records(page, cfg):
    page.evaluate(
        """
        () => {
          const target = document.querySelector('#records, #recordList, .record-list');
          if (target) target.scrollIntoView({block: 'start', inline: 'nearest'});
        }
        """
    )
    page.wait_for_timeout(cfg.stable_wait_ms)


def click_page(page, target):
    return page.evaluate(
        """
        (target) => {
          const buttons = [...document.querySelectorAll('button.pagination-button')]
            .filter((button) => (button.textContent || button.innerText || '').trim() === String(target));
          if (!buttons.length) return false;
          buttons[0].scrollIntoView({block: 'center', inline: 'nearest'});
          buttons[0].click();
          return true;
        }
        """,
        target,
    )


def crawl_live_site(cfg):
    observed = []
    pages = []

    with BrowserSession(cfg) as page:
        print("[reconcile] Opening live site...")
        goto_release_page(page, cfg)
        wait_for_rows(page, cfg)
        scroll_to_records(page, cfg)
        validate_release_scope(page, cfg)

        site_count_label = extract_site_count_label(page)
        page_number = active_page_number(page) or 1
        previous_keys = None

        while page_number <= cfg.max_pages:
            rows = extract_rendered_rows(page, page_number)
            keys = [record_key(row["title"], row["type"]) for row in rows]

            if page_number > 1 and keys and keys == previous_keys:
                break

            observed.extend(rows)
            pages.append({"page": page_number, "visible_count": len(rows)})
            print(f"[reconcile] Page {page_number}: {len(rows)} visible records")

            previous_keys = keys
            next_page = page_number + 1
            if not click_page(page, next_page):
                break
            page.wait_for_timeout(cfg.stable_wait_ms)
            wait_for_rows(page, cfg)
            page_number = active_page_number(page) or next_page

    return observed, pages, site_count_label


def crawl_debug_html(cfg, html_dir):
    from playwright.sync_api import sync_playwright

    observed = []
    pages = []
    site_count_label = None
    files = [
        path for path in Path(html_dir).glob("*.html")
        if re.search(r"(?:^|_)page_(\d+)\.html$", path.name)
    ]
    files = sorted(files, key=lambda p: int(re.search(r"(?:^|_)page_(\d+)\.html$", p.name).group(1)))

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 1365, "height": 900})
        for file_path in files:
            page_number = int(re.search(r"(?:^|_)page_(\d+)\.html$", file_path.name).group(1))
            page.set_content(file_path.read_text(encoding="utf-8", errors="replace"))
            page.wait_for_timeout(100)
            scroll_to_records(page, cfg)
            if site_count_label is None:
                site_count_label = extract_site_count_label(page)
            rows = extract_rendered_rows(page, page_number)
            observed.extend(rows)
            pages.append({"page": page_number, "visible_count": len(rows), "source": str(file_path)})
            print(f"[reconcile] {file_path.name}: {len(rows)} visible records")
        browser.close()

    return observed, pages, site_count_label


def load_index_records(index_path):
    data = json.loads(Path(index_path).read_text(encoding="utf-8"))
    records = []

    for asset_name, rec in sorted((data.get("records") or {}).items()):
        title = rec.get("asset_name") or asset_name
        record_type = rec.get("document_type") or rec.get("row_type") or ".PDF"
        records.append(
            {
                "title": title,
                "type": normalize_type(record_type),
                "key": record_key(title, record_type),
                "seen_on_pages": rec.get("seen_on_pages") or [],
                "url": rec.get("url") or "",
            }
        )

    return records


def aaro_record_key(item):
    return clean_text(item.get("id")) or normalize_title(item.get("title")) or clean_text(item.get("mp4_url"))


def aaro_record(item):
    return {
        "id": clean_text(item.get("id")),
        "title": clean_text(item.get("title")),
        "mp4_url": clean_text(item.get("mp4_url")),
        "dvids_url": clean_text(item.get("dvids_url")),
        "description": clean_text(item.get("description")),
        "key": aaro_record_key(item),
    }


def load_aaro_index_records(index_path):
    data = json.loads(Path(index_path).read_text(encoding="utf-8"))
    records = []
    for key, item in sorted((data.get("items") or {}).items()):
        rec = aaro_record(item)
        if not rec["id"]:
            rec["id"] = clean_text(key)
            rec["key"] = aaro_record_key(rec)
        records.append(rec)
    return records


def crawl_aaro_site(html_file=None):
    from aaro_rip import AARO_URL, extract_items, fetch_html

    if html_file:
        source_path = Path(html_file)
        html = fetch_html(str(source_path))
        source = {"mode": "aaro_saved_html", "html_file": str(source_path)}
    else:
        print("[reconcile] Opening AARO live site...")
        html = fetch_html()
        source = {"mode": "aaro_live_site", "start_url": AARO_URL}

    found = extract_items(html)
    observed = [aaro_record(item) for item in found]
    return observed, source


def compare_aaro(observed, index_records):
    observed_counts = Counter(row["key"] for row in observed)
    index_counts = Counter(row["key"] for row in index_records)
    observed_keys = set(observed_counts)
    index_keys = set(index_counts)
    site_only = [row for row in observed if row["key"] not in index_keys]
    index_only = [row for row in index_records if row["key"] not in observed_keys]
    changed_urls = []

    index_by_key = {row["key"]: row for row in index_records}
    for row in observed:
        indexed = index_by_key.get(row["key"])
        if not indexed:
            continue
        if row.get("mp4_url") and indexed.get("mp4_url") and row["mp4_url"] != indexed["mp4_url"]:
            changed_urls.append(
                {
                    "key": row["key"],
                    "title": row.get("title"),
                    "site_mp4_url": row.get("mp4_url"),
                    "index_mp4_url": indexed.get("mp4_url"),
                }
            )

    return {
        "generated_at": now_iso(),
        "summary": {
            "observed_site_count": len(observed),
            "local_index_count": len(index_records),
            "observed_unique_key_count": len(observed_keys),
            "index_unique_key_count": len(index_keys),
            "site_only_count": len(site_only),
            "index_only_count": len(index_only),
            "changed_mp4_url_count": len(changed_urls),
            "observed_missing_mp4_url_count": sum(1 for row in observed if not row.get("mp4_url")),
            "index_missing_mp4_url_count": sum(1 for row in index_records if not row.get("mp4_url")),
        },
        "site_records": observed,
        "index_records": index_records,
        "records_present_on_site_absent_from_index": site_only,
        "records_in_index_not_found_on_site": index_only,
        "changed_mp4_urls": changed_urls,
        "duplicate_normalized_records": {
            "site": find_duplicates(observed),
            "index": find_duplicates(index_records),
        },
    }


def write_aaro_outputs(cfg, report):
    cfg.ensure_dirs()
    report_path = cfg.data_dir / "reconciliation_report_aaro.json"
    missing_path = cfg.data_dir / "missing_records_aaro.txt"

    report_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    lines = [
        f"{row.get('id', '')}\t{row.get('title', '')}\t{row.get('mp4_url', '')}"
        for row in report["records_present_on_site_absent_from_index"]
    ]
    changed = report.get("changed_mp4_urls") or []
    if changed:
        if lines:
            lines.append("")
        lines.append("# Indexed AARO records whose MP4 URL changed on the live site")
        lines.extend(
            f"{row.get('key', '')}\t{row.get('title', '')}\tSITE={row.get('site_mp4_url', '')}\tINDEX={row.get('index_mp4_url', '')}"
            for row in changed
        )

    missing_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return report_path, missing_path


def reconcile_aaro(cfg, index_path, html_file=None):
    print("[reconcile] Target:  AARO")
    print(f"[reconcile] Index:   {index_path}")
    observed, source = crawl_aaro_site(html_file)

    if not observed:
        raise RuntimeError("No AARO records were observed; refusing to overwrite reconciliation outputs.")

    index_records = load_aaro_index_records(index_path)
    report = compare_aaro(observed, index_records)
    report["source"] = source
    report["index_path"] = str(index_path)

    report_path, missing_path = write_aaro_outputs(cfg, report)

    summary = report["summary"]
    print("\n=== AARO Reconciliation Summary ===")
    print(f"Observed site count:      {summary['observed_site_count']}")
    print(f"Local index count:        {summary['local_index_count']}")
    print(f"Site unique keys:         {summary['observed_unique_key_count']}")
    print(f"Index unique keys:        {summary['index_unique_key_count']}")
    print(f"Site only:                {summary['site_only_count']}")
    print(f"Index only:               {summary['index_only_count']}")
    print(f"Changed MP4 URLs:         {summary['changed_mp4_url_count']}")
    print(f"Site records missing MP4: {summary['observed_missing_mp4_url_count']}")
    print(f"Index records missing MP4:{summary['index_missing_mp4_url_count']}")
    print(f"Report:                   {report_path}")
    print(f"Missing records:          {missing_path}")


def find_duplicates(records):
    grouped = defaultdict(list)
    for record in records:
        grouped[record["key"]].append(record)
    return {key: values for key, values in grouped.items() if len(values) > 1}


def counts_by_media(records):
    counts = Counter(media_family(record.get("type")) for record in records)
    return {
        "pdfs": counts.get("pdfs", 0),
        "videos": counts.get("videos", 0),
        "images": counts.get("images", 0),
        "audio": counts.get("audio", 0),
        "other": counts.get("other", 0),
    }


def compare(observed, index_records, site_count_label):
    for row in observed:
        row["type"] = normalize_type(row.get("type"))
        row["key"] = record_key(row.get("title"), row.get("type"))

    observed_counts = Counter(row["key"] for row in observed)
    index_counts = Counter(row["key"] for row in index_records)
    observed_keys = set(observed_counts)
    index_keys = set(index_counts)
    site_only = [row for row in observed if row["key"] not in index_keys]
    index_only = [row for row in index_records if row["key"] not in observed_keys]
    site_instance_only = []
    index_instance_only = []

    for key, count in observed_counts.items():
        extra = count - index_counts.get(key, 0)
        if extra > 0:
            site_instance_only.extend([row for row in observed if row["key"] == key][-extra:])

    for key, count in index_counts.items():
        extra = count - observed_counts.get(key, 0)
        if extra > 0:
            index_instance_only.extend([row for row in index_records if row["key"] == key][-extra:])

    return {
        "generated_at": now_iso(),
        "summary": {
            "observed_site_count": len(observed),
            "site_reported_count": site_count_label,
            "local_index_count": len(index_records),
            "observed_unique_normalized_count": len(observed_keys),
            "index_unique_normalized_count": len(index_keys),
            "observed_media_counts": counts_by_media(observed),
            "index_media_counts": counts_by_media(index_records),
            "site_only_count": len(site_only),
            "index_only_count": len(index_only),
            "site_row_instances_absent_from_index_count": len(site_instance_only),
            "index_row_instances_absent_from_site_count": len(index_instance_only),
        },
        "site_records": observed,
        "index_records": index_records,
        "missing_records": site_only,
        "records_present_on_site_absent_from_index": site_only,
        "records_in_index_not_found_on_site": index_only,
        "site_row_instances_absent_from_index": site_instance_only,
        "index_row_instances_absent_from_site": index_instance_only,
        "duplicate_normalized_records": {
            "site": find_duplicates(observed),
            "index": find_duplicates(index_records),
        },
    }


def write_outputs(cfg, report, index_path):
    cfg.ensure_dirs()
    suffix = Path(index_path).stem.replace("index_", "")
    report_path = cfg.data_dir / f"reconciliation_report_{suffix}.json"
    missing_path = cfg.data_dir / f"missing_records_{suffix}.txt"

    report_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    missing = report["records_present_on_site_absent_from_index"]
    missing_instances = report["site_row_instances_absent_from_index"]
    lines = [
        f"{row.get('page', '?')}\t{row.get('type', '')}\t{row.get('title', '')}"
        for row in missing
    ]
    if missing_instances:
        if lines:
            lines.append("")
        lines.append("# Site row instances absent from index after normalized duplicate collapse")
        lines.extend(
            f"{row.get('page', '?')}\t{row.get('type', '')}\t{row.get('title', '')}"
            for row in missing_instances
        )
    missing_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return report_path, missing_path


def parse_args():
    parser = argparse.ArgumentParser(
        description="Audit rendered war.gov UFO or AARO records against a selected local index."
    )
    parser.add_argument(
        "--index",
        default=None,
        help="Path to an index_release_N.json or aaro_index.json file. If omitted, choose from detected indexes.",
    )
    parser.add_argument(
        "--release",
        type=int,
        default=None,
        help="Release number to reconcile, for example 1 or 2. Uses war_ufo_data/data/index_release_N.json.",
    )
    parser.add_argument(
        "--aaro",
        action="store_true",
        help="Reconcile war_ufo_data/data/aaro_index.json against the AARO imagery page.",
    )
    parser.add_argument(
        "--aaro-html",
        default=None,
        help="Saved AARO HTML/source file to reconcile instead of fetching the live AARO page.",
    )
    parser.add_argument(
        "--from-debug-html",
        action="store_true",
        help="Audit saved war_ufo_data/debug/html/page_*.html snapshots instead of the live site.",
    )
    parser.add_argument(
        "--html-dir",
        default=None,
        help="Directory containing page_*.html snapshots for --from-debug-html.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    cfg = Config.load()

    explicit_targets = sum(1 for value in (args.index, args.release, args.aaro) if value)
    if explicit_targets > 1:
        raise ValueError("Use only one target selector: --index, --release, or --aaro.")
    if args.aaro_html and not args.aaro and not (args.index and is_aaro_index_path(args.index)):
        raise ValueError("--aaro-html can only be used with --aaro or --index war_ufo_data/data/aaro_index.json.")

    if args.release:
        cfg.set_release(args.release, save=False)
        index_path = cfg.data_dir / f"index_release_{args.release}.json"
    elif args.aaro:
        index_path = cfg.data_dir / AARO_INDEX_NAME
    elif args.index:
        index_path = Path(args.index)
        apply_release_from_index(cfg, index_path)
    else:
        index_path = select_index_file(cfg)
        apply_release_from_index(cfg, index_path)

    if not index_path.exists():
        raise FileNotFoundError(f"Index not found: {index_path}")

    if is_aaro_index_path(index_path):
        reconcile_aaro(cfg, index_path, html_file=args.aaro_html)
        return

    if args.from_debug_html:
        html_dir = Path(args.html_dir) if args.html_dir else cfg.debug_dir / "html"
        observed, pages, site_count_label = crawl_debug_html(cfg, html_dir)
        source = {"mode": "debug_html", "html_dir": str(html_dir)}
    else:
        print(f"[reconcile] Release: {cfg.release}")
        print(f"[reconcile] URL:     {cfg.start_url}")
        print(f"[reconcile] Index:   {index_path}")
        observed, pages, site_count_label = crawl_live_site(cfg)
        source = {"mode": "live_site", "start_url": cfg.start_url}

    if not observed:
        raise RuntimeError(
            "No rendered site records were observed; refusing to overwrite reconciliation outputs."
        )

    index_records = load_index_records(index_path)
    report = compare(observed, index_records, site_count_label)
    report["source"] = source
    report["pages"] = pages
    report["index_path"] = str(index_path)

    report_path, missing_path = write_outputs(cfg, report, index_path)

    summary = report["summary"]
    print("\n=== Reconciliation Summary ===")
    print(f"Observed site count: {summary['observed_site_count']}")
    print(f"Site reported count: {summary['site_reported_count']}")
    print(f"Local index count:   {summary['local_index_count']}")
    print(f"Site unique keys:    {summary['observed_unique_normalized_count']}")
    print(f"Index unique keys:   {summary['index_unique_normalized_count']}")
    print(f"Site only:           {summary['site_only_count']}")
    print(f"Index only:          {summary['index_only_count']}")
    print(f"Missing instances:   {summary['site_row_instances_absent_from_index_count']}")
    print(
        "Observed media:      "
        f"PDFs={summary['observed_media_counts']['pdfs']} "
        f"Videos={summary['observed_media_counts']['videos']} "
        f"Images={summary['observed_media_counts']['images']} "
        f"Audio={summary['observed_media_counts']['audio']} "
        f"Other={summary['observed_media_counts']['other']}"
    )
    print(f"Report:              {report_path}")
    print(f"Missing records:     {missing_path}")


if __name__ == "__main__":
    main()
