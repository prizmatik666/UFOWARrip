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


REPORT_NAME = "reconciliation_report.json"
MISSING_NAME = "missing_records.txt"


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
        page.goto(cfg.start_url, wait_until="domcontentloaded", timeout=90000)
        wait_for_rows(page, cfg)
        scroll_to_records(page, cfg)

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
    files = sorted(
        Path(html_dir).glob("page_*.html"),
        key=lambda p: int(re.search(r"page_(\d+)", p.name).group(1)),
    )

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 1365, "height": 900})
        for file_path in files:
            page_number = int(re.search(r"page_(\d+)", file_path.name).group(1))
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


def write_outputs(cfg, report):
    cfg.ensure_dirs()
    report_path = cfg.data_dir / REPORT_NAME
    missing_path = cfg.data_dir / MISSING_NAME

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
        description="Audit rendered war.gov UFO records against war_ufo_data/data/index.json."
    )
    parser.add_argument("--index", default=None, help="Path to index.json. Defaults to configured data dir.")
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
    index_path = Path(args.index) if args.index else cfg.data_dir / "index.json"

    if args.from_debug_html:
        html_dir = Path(args.html_dir) if args.html_dir else cfg.debug_dir / "html"
        observed, pages, site_count_label = crawl_debug_html(cfg, html_dir)
        source = {"mode": "debug_html", "html_dir": str(html_dir)}
    else:
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

    report_path, missing_path = write_outputs(cfg, report)

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
        f"Other={summary['observed_media_counts']['other']}"
    )
    print(f"Report:              {report_path}")
    print(f"Missing records:     {missing_path}")


if __name__ == "__main__":
    main()
