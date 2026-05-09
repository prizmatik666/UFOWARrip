# UFOWARrip
# Created by Prizmatik
# https://github.com/prizmatik666/UFOWARrip

import json
import re
from urllib.parse import unquote, urlsplit

from core.browser_session import BrowserSession
from core.index_store import load_index, save_index, export_urls
from core.logger import log, now_iso


def clean_text(s):
    return re.sub(r"\s+", " ", (s or "").strip())


def norm(s):
    return clean_text(s).lower()


def loose_norm(s):
    return re.sub(r"[^a-z0-9]+", "_", norm(s)).strip("_")


def safe_name(s):
    return re.sub(r"[^a-zA-Z0-9_.-]+", "_", s)[:120]


def url_extension(url):
    path = unquote(urlsplit(url or "").path).lower()
    match = re.search(r"\.[a-z0-9]{2,5}$", path)
    return match.group(0) if match else None


def is_durable_pdf_url(url):
    parts = urlsplit(url or "")
    host = (parts.netloc or "").lower()
    path = unquote(parts.path or "").lower()

    if parts.scheme not in {"http", "https"}:
        return False

    if host not in {"war.gov", "www.war.gov"}:
        return False

    if url_extension(url) != ".pdf":
        return False

    return "/medialink/ufo/" in path


def parsed_row_type(row):
    cells = row.get("cells") or []

    for cell in reversed(cells):
        value = (cell or "").strip().upper()
        if value.startswith("[.") and value.endswith("]"):
            return value.strip("[]")
        if value.startswith(".") and len(value) <= 8:
            return value

    return (row.get("document_type") or row.get("row_type") or "").strip().upper()


def is_pdf_row(row):
    text = (row.get("text") or " ".join(row.get("cells") or "") or "").upper()
    row_type = parsed_row_type(row)

    return "[.PDF]" in text or ".PDF" in text or row_type == ".PDF"


def append_harvest_event(rec, event):
    events = rec.setdefault("harvest_events", [])
    events.append({"ts": now_iso(), **event})
    del events[:-25]


def mark_harvest_success(rec, url, method, page):
    old_url = rec.get("url")

    if old_url and old_url != url:
        previous = rec.setdefault("previous_urls", [])
        if old_url not in previous:
            previous.append(old_url)

        if not old_url.lower().startswith("blob:"):
            rec.setdefault("candidate_url", old_url)

    rec["url"] = url
    rec["url_source"] = "clicked_download_button"
    rec["confidence"] = "high"
    rec["harvested_at"] = now_iso()
    rec["last_harvest_attempt_at"] = rec["harvested_at"]
    rec["harvest_method"] = method
    rec["harvest_status"] = "ok"
    rec["harvest_retryable"] = False
    rec.pop("harvest_error", None)
    rec["harvest_attempts"] = int(rec.get("harvest_attempts") or 0) + 1
    rec["seen_on_pages"] = sorted(set((rec.get("seen_on_pages") or []) + [page]))
    append_harvest_event(rec, {
        "status": "ok",
        "method": method,
        "url": url,
        "page": page,
    })


def mark_harvest_failure(rec, error, page, method=None, url=None):
    ts = now_iso()
    rec["harvest_status"] = f"failed: {error}"
    rec["harvest_error"] = str(error)
    rec["harvest_failed_at"] = ts
    rec["last_harvest_attempt_at"] = ts
    rec["harvest_retryable"] = True
    rec["harvest_attempts"] = int(rec.get("harvest_attempts") or 0) + 1
    append_harvest_event(rec, {
        "status": "failed",
        "error": str(error),
        "method": method,
        "url": url,
        "page": page,
    })


def repair_invalid_harvest_urls(index):
    repaired = 0

    for rec in index.get("records", {}).values():
        url = rec.get("url") or ""

        if (
            rec.get("url_source") != "clicked_download_button"
            or rec.get("confidence") != "high"
            or is_durable_pdf_url(url)
        ):
            continue

        previous = rec.setdefault("previous_urls", [])
        if url and url not in previous:
            previous.append(url)

        rec["bad_harvest_url"] = url
        fallback = rec.get("candidate_url")

        if fallback and not str(fallback).lower().startswith("blob:"):
            rec["url"] = fallback
            rec["url_source"] = rec.get("candidate_url_source") or "previous_candidate_url"
            rec["confidence"] = "medium"

        rec["harvest_status"] = f"failed: invalid captured URL: {url}"
        rec["harvest_error"] = f"invalid captured URL: {url}"
        rec["harvest_retryable"] = True
        rec["harvest_failed_at"] = now_iso()
        append_harvest_event(rec, {
            "status": "failed",
            "error": "invalid captured URL",
            "url": url,
            "method": rec.get("harvest_method"),
            "page": None,
        })
        repaired += 1

    return repaired


def append_observation(cfg, data):
    cfg.ensure_dirs()
    path = cfg.data_dir / "observations.jsonl"
    path.open("a", encoding="utf-8").write(json.dumps(data, sort_keys=True) + "\n")


def save_debug(cfg, page, asset, label):
    safe = safe_name(asset)
    cfg.ensure_dirs()

    try:
        page.screenshot(
            path=str(cfg.debug_dir / "screenshots" / f"harvest_{safe}_{label}.png"),
            full_page=True,
        )
    except Exception:
        pass

    try:
        (cfg.debug_dir / "html" / f"harvest_{safe}_{label}.html").write_text(
            page.content(),
            encoding="utf-8",
            errors="replace",
        )
    except Exception:
        pass

    try:
        text = page.evaluate("() => document.body ? document.body.innerText : ''")
        (cfg.debug_dir / "text" / f"harvest_{safe}_{label}.txt").write_text(
            text or "",
            encoding="utf-8",
            errors="replace",
        )
    except Exception:
        pass


def active_page_number(page):
    try:
        value = page.evaluate(
            """
            () => {
              const active = document.querySelector('.pagination-button.is-active');
              return active ? (active.innerText || '').trim() : '';
            }
            """
        )
        return int(value) if str(value).isdigit() else None
    except Exception:
        return None


def wait_for_records_ready(page, cfg):
    for _ in range(30):
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


def scroll_to_records_table(page, cfg):
    """
    Move the browser to the released-records section before row extraction.
    The site starts far above the records list, so viewport-only scans can
    otherwise report no rows even when the current page has records.
    """
    page.evaluate(
        """
        () => {
          const selectors = [
            '#records',
            '[aria-label="Released records"]',
            '#recordList',
            '.record-list'
          ];

          const target = selectors
            .map(sel => document.querySelector(sel))
            .find(Boolean);

          if (target) {
            target.scrollIntoView({block: 'start', inline: 'nearest'});
            window.scrollBy(0, -90);
            return true;
          }

          const release = document.querySelector('#release');
          if (release) {
            release.scrollIntoView({block: 'start', inline: 'nearest'});
            window.scrollBy(0, window.innerHeight * 0.8);
          }

          return false;
        }
        """
    )
    page.wait_for_timeout(cfg.stable_wait_ms)

    for _ in range(8):
        rows = extract_visible_table_rows(page)
        if rows:
            return True

        page.evaluate("() => window.scrollBy(0, Math.floor(window.innerHeight * 0.75))")
        page.wait_for_timeout(max(250, int(cfg.stable_wait_ms / 2)))

    return False


def extract_visible_table_rows(page):
    """
    Returns rendered record rows from the current site pagination page.
    The primary path uses the page-local #recordList buttons so we never
    harvest by sorted index order or stale global matching.
    """
    return page.evaluate(
        """
        () => {
          const rendered = el => {
            const r = el.getBoundingClientRect();
            const s = window.getComputedStyle(el);
            return r.width > 20 &&
                   r.height > 8 &&
                   s.display !== 'none' &&
                   s.visibility !== 'hidden' &&
                   s.opacity !== '0';
          };

          const recordRows = [...document.querySelectorAll(
            '#recordList .record-row, .record-list .record-row, [data-record-trigger]'
          )].filter(rendered);

          if (recordRows.length) {
            return recordRows.map((el, i) => {
              const text = (el.innerText || '').trim();
              const titleEl = el.querySelector('.record-title');
              const title = titleEl
                ? (titleEl.textContent || titleEl.innerText || '').trim()
                : '';
              const cells = [...el.querySelectorAll('.record-title, .record-meta')]
                .map(x => (x.textContent || x.innerText || '').trim())
                .filter(Boolean);
              const first = title || (cells.length ? cells[0] : text.split('\\n')[0] || '');
              const typeCell = [...cells].reverse().find(x => /^\\[?\\.[a-z0-9]+\\]?$/i.test(x)) || '';
              const parsedType = typeCell ? typeCell.replace(/[\\[\\]]/g, '').toUpperCase() : '';
              const rect = el.getBoundingClientRect();

              return {
                row_index: i,
                record_id: el.getAttribute('data-record-id') || '',
                text,
                cells: cells.length ? cells : text.split('\\n').map(x => x.trim()).filter(Boolean),
                first_cell: first,
                row_type: parsedType,
                document_type: parsedType,
                tag: el.tagName,
                classes: String(el.className || ''),
                in_viewport: rect.bottom > 0 && rect.top < window.innerHeight
              };
            });
          }

          const rows = [...document.querySelectorAll('tr, button')]
            .filter(rendered)
            .map((el, i) => {
              const text = (el.innerText || '').trim();
              const cells = text.split('\\n').map(x => x.trim()).filter(Boolean);
              const typeCell = [...cells].reverse().find(x => /^\\[?\\.[a-z0-9]+\\]?$/i.test(x)) || '';
              const parsedType = typeCell ? typeCell.replace(/[\\[\\]]/g, '').toUpperCase() : '';
              const rect = el.getBoundingClientRect();

              return {
                row_index: i,
                record_id: el.getAttribute('data-record-id') || '',
                text,
                cells,
                first_cell: cells.length ? cells[0] : '',
                row_type: parsedType,
                document_type: parsedType,
                tag: el.tagName,
                classes: String(el.className || ''),
                in_viewport: rect.bottom > 0 && rect.top < window.innerHeight
              };
            })
            .filter(r => {
              if (!r.first_cell) return false;

              const first = r.first_cell.toUpperCase();

              if (['PREV', 'NEXT', 'DOWNLOAD', 'CLOSE', 'X'].includes(first)) return false;
              if (['FILES', 'AGENCY', 'RELEASE DATE', 'INCIDENT DATE', 'INCIDENT LOCATION'].includes(first)) return false;

              // Filename-ish rows
              return first.includes('_') || first.includes('-') || /\\d/.test(first);
            });

          return rows;
        }
        """
    )


def normalize_asset_from_row(row):
    first = row.get("first_cell") or ""
    first = clean_text(first)

    if not first:
        return None

    bad = {"PREV", "NEXT", "DOWNLOAD", "CLOSE", "X"}
    if first.upper() in bad:
        return None

    return first


def click_row_by_index(page, row):
    return page.evaluate(
        """
        (targetRow) => {
          const rendered = el => {
            const r = el.getBoundingClientRect();
            const s = window.getComputedStyle(el);
            return r.width > 20 &&
                   r.height > 8 &&
                   s.display !== 'none' &&
                   s.visibility !== 'hidden' &&
                   s.opacity !== '0';
          };

          const recordRows = [...document.querySelectorAll(
            '#recordList .record-row, .record-list .record-row, [data-record-trigger]'
          )].filter(rendered);

          let rows = recordRows.length
            ? recordRows
            : [...document.querySelectorAll('tr, button')].filter(rendered);

          let el = null;

          if (targetRow && targetRow.record_id) {
            el = rows.find(x => x.getAttribute('data-record-id') === targetRow.record_id) || null;
          }

          if (!el && targetRow && targetRow.first_cell) {
            const wanted = String(targetRow.first_cell).trim().toLowerCase();
            el = rows.find(x => {
              const title = x.querySelector('.record-title');
              const first = title
                ? (title.textContent || title.innerText || '').trim()
                : ((x.innerText || '').trim().split('\\n')[0] || '').trim();
              return first.toLowerCase() === wanted;
            }) || null;
          }

          if (!el && targetRow) {
            el = rows[targetRow.row_index];
          }

          if (!el) {
            return {clicked:false, reason:'row_not_found', visible_count: rows.length};
          }

          el.scrollIntoView({block:'center', inline:'center'});
          el.click();

          return {
            clicked:true,
            text:(el.innerText || '').trim().slice(0, 500),
            tag:el.tagName,
            classes:String(el.className || ''),
            visible_count:rows.length
          };
        }
        """,
        row,
    )


def wait_for_modal(page, cfg):
    for _ in range(24):
        found = page.evaluate(
            """
            () => {
              const visible = el => {
                const r = el.getBoundingClientRect();
                const s = window.getComputedStyle(el);
                return r.width > 20 &&
                       r.height > 20 &&
                       s.display !== 'none' &&
                       s.visibility !== 'hidden' &&
                       s.opacity !== '0';
              };

              const selectors = [
                '[role="dialog"]',
                '[aria-modal="true"]',
                '.modal',
                '.modal-dialog',
                '.modal-content',
                '#record-modal',
                '.record-modal'
              ];

              for (const sel of selectors) {
                const el = document.querySelector(sel);
                if (el && visible(el)) return true;
              }

              const bodyText = document.body ? document.body.innerText.toLowerCase() : '';
              return bodyText.includes('asset file name') &&
                     bodyText.includes('document type') &&
                     bodyText.includes('download');
            }
            """
        )

        if found:
            return True

        page.wait_for_timeout(max(250, int(cfg.stable_wait_ms / 2)))

    return False


def find_download_candidates(page):
    return page.evaluate(
        """
        () => {
          const visible = el => {
            const r = el.getBoundingClientRect();
            const s = window.getComputedStyle(el);
            return r.width > 5 &&
                   r.height > 5 &&
                   s.display !== 'none' &&
                   s.visibility !== 'hidden' &&
                   s.opacity !== '0';
          };

          const scopeSelectors = [
            '[role="dialog"]',
            '[aria-modal="true"]',
            '.modal',
            '.modal-dialog',
            '.modal-content',
            '#record-modal',
            '.record-modal'
          ];

          let scopes = [];

          for (const sel of scopeSelectors) {
            scopes.push(...[...document.querySelectorAll(sel)].filter(visible));
          }

          if (!scopes.length) scopes = [document.body];

          const out = [];

          for (const scope of scopes) {
            const nodes = [...scope.querySelectorAll('button, a')]
              .filter(visible)
              .filter(el => !el.disabled && el.getAttribute('aria-disabled') !== 'true')
              .map((el, i) => ({
                i,
                tag: el.tagName,
                text: (el.innerText || '').trim(),
                href: el.href || el.getAttribute('href') || '',
                aria: el.getAttribute('aria-label') || '',
                title: el.getAttribute('title') || '',
                onclick: el.getAttribute('onclick') || '',
                classes: String(el.className || '')
              }));

            for (const n of nodes) {
              const blob = JSON.stringify(n).toLowerCase();
              if (blob.includes('download')) out.push(n);
            }
          }

          return out;
        }
        """
    )


def click_download_button(page):
    return page.evaluate(
        """
        () => {
          const visible = el => {
            const r = el.getBoundingClientRect();
            const s = window.getComputedStyle(el);
            return r.width > 5 &&
                   r.height > 5 &&
                   s.display !== 'none' &&
                   s.visibility !== 'hidden' &&
                   s.opacity !== '0';
          };

          const scopeSelectors = [
            '[role="dialog"]',
            '[aria-modal="true"]',
            '.modal',
            '.modal-dialog',
            '.modal-content',
            '#record-modal',
            '.record-modal'
          ];

          let scopes = [];

          for (const sel of scopeSelectors) {
            scopes.push(...[...document.querySelectorAll(sel)].filter(visible));
          }

          if (!scopes.length) scopes = [document.body];

          const buttons = [];

          for (const scope of scopes) {
            buttons.push(...[...scope.querySelectorAll('button, a')].filter(visible));
          }

          const candidates = buttons.filter(el => {
            if (el.disabled || el.getAttribute('aria-disabled') === 'true') return false;

            const blob = JSON.stringify({
              text: el.innerText || '',
              href: el.href || el.getAttribute('href') || '',
              aria: el.getAttribute('aria-label') || '',
              title: el.getAttribute('title') || '',
              onclick: el.getAttribute('onclick') || '',
              classes: String(el.className || '')
            }).toLowerCase();

            return blob.includes('download');
          });

          if (!candidates.length) return false;

          candidates[0].scrollIntoView({block:'center', inline:'center'});
          candidates[0].click();
          return true;
        }
        """
    )


def wait_for_download_button_ready(page, cfg):
    for _ in range(24):
        ready = page.evaluate(
            """
            () => {
              const visible = el => {
                const r = el.getBoundingClientRect();
                const s = window.getComputedStyle(el);
                return r.width > 5 &&
                       r.height > 5 &&
                       s.display !== 'none' &&
                       s.visibility !== 'hidden' &&
                       s.opacity !== '0';
              };

              const scopes = [
                '[role="dialog"]',
                '[aria-modal="true"]',
                '.modal',
                '.modal-dialog',
                '.modal-content',
                '#record-modal',
                '.record-modal'
              ].flatMap(sel => [...document.querySelectorAll(sel)].filter(visible));

              for (const scope of (scopes.length ? scopes : [document.body])) {
                const buttons = [...scope.querySelectorAll('button, a')].filter(visible);
                for (const el of buttons) {
                  const blob = JSON.stringify({
                    text: el.innerText || '',
                    href: el.href || el.getAttribute('href') || '',
                    aria: el.getAttribute('aria-label') || '',
                    title: el.getAttribute('title') || '',
                    onclick: el.getAttribute('onclick') || '',
                    classes: String(el.className || '')
                  }).toLowerCase();

                  if (
                    blob.includes('download') &&
                    !el.disabled &&
                    el.getAttribute('aria-disabled') !== 'true'
                  ) {
                    return true;
                  }
                }
              }

              return false;
            }
            """
        )

        if ready:
            return True

        page.wait_for_timeout(max(250, int(cfg.stable_wait_ms / 2)))

    return False


def wait_for_pdf_url(pg, cfg):
    for _ in range(40):
        url = pg.url or ""

        if is_durable_pdf_url(url):
            return url

        pg.wait_for_timeout(300)

    return pg.url


def capture_download_url(page, cfg):
    if not wait_for_download_button_ready(page, cfg):
        return None, "download_button_not_ready", find_download_candidates(page)

    candidates = find_download_candidates(page)

    # Most common on this site: click Download opens a new tab/page.
    try:
        with page.context.expect_page(timeout=10000) as new_page_info:
            clicked = click_download_button(page)

            if not clicked:
                return None, "download_button_not_found", candidates

        new_page = new_page_info.value
        actual_url = wait_for_pdf_url(new_page, cfg)
        try:
            new_page.close()
        except Exception:
            pass

        if is_durable_pdf_url(actual_url):
            return actual_url, "new_page", candidates

        return None, f"new_page_no_pdf_url:{actual_url}", candidates

    except Exception:
        pass

    # Fallback: actual download event.
    try:
        with page.expect_download(timeout=10000) as download_info:
            clicked = click_download_button(page)

            if not clicked:
                return None, "download_button_not_found", candidates

        download = download_info.value
        actual_url = download.url

        if is_durable_pdf_url(actual_url):
            return actual_url, "download_event", candidates

        if actual_url:
            return None, f"download_event_no_pdf_url:{actual_url}", candidates

    except Exception:
        pass

    # Fallback: same-tab navigation.
    before = page.url

    try:
        clicked = click_download_button(page)

        if not clicked:
            return None, "download_button_not_found", candidates

        for _ in range(40):
            after = page.url

            if after != before and is_durable_pdf_url(after):
                actual_url = after

                try:
                    page.go_back(wait_until="domcontentloaded", timeout=30000)
                    page.wait_for_timeout(cfg.stable_wait_ms)
                except Exception:
                    pass

                return actual_url, "same_tab", candidates

            page.wait_for_timeout(300)

    except Exception:
        pass

    return None, "no_url_captured", candidates


def close_modal(page, cfg=None):
    try:
        page.evaluate(
            """
            () => {
              const visible = el => {
                const r = el.getBoundingClientRect();
                const s = window.getComputedStyle(el);
                return r.width > 5 &&
                       r.height > 5 &&
                       s.display !== 'none' &&
                       s.visibility !== 'hidden' &&
                       s.opacity !== '0';
              };

              const candidates = [...document.querySelectorAll('button, a')]
                .filter(visible)
                .filter(el => {
                  const t = (el.innerText || '').trim().toLowerCase();
                  const a = (el.getAttribute('aria-label') || '').toLowerCase();
                  const cls = String(el.className || '').toLowerCase();
                  return t === 'close' ||
                         t === 'x' ||
                         t === '×' ||
                         a.includes('close') ||
                         cls.includes('close');
                });

              if (candidates.length) {
                candidates[0].click();
                return true;
              }

              document.dispatchEvent(new KeyboardEvent('keydown', {key:'Escape'}));
              return false;
            }
            """
        )

        if cfg:
            page.wait_for_timeout(500)

    except Exception:
        pass


def click_next_page(page, cfg):
    before = None
    try:
        rows = extract_visible_table_rows(page)
        before = normalize_asset_from_row(rows[0]) if rows else None
    except Exception:
        before = None

    clicked = page.evaluate(
        """
        () => {
          const visible = el => {
            const r = el.getBoundingClientRect();
            const s = window.getComputedStyle(el);
            return r.width > 5 &&
                   r.height > 5 &&
                   s.display !== 'none' &&
                   s.visibility !== 'hidden' &&
                   s.opacity !== '0';
          };

          let candidates = [...document.querySelectorAll('button.pagination-next, a.pagination-next')]
            .filter(visible)
            .filter(el => !el.disabled && el.getAttribute('aria-disabled') !== 'true');

          if (!candidates.length) {
            candidates = [...document.querySelectorAll('button, a')]
            .filter(visible)
            .filter(el => (el.innerText || '').trim().toUpperCase() === 'NEXT')
            .filter(el => !el.disabled && el.getAttribute('aria-disabled') !== 'true');
          }

          if (!candidates.length) return false;

          candidates[candidates.length - 1].scrollIntoView({block:'center', inline:'center'});
          candidates[candidates.length - 1].click();
          return true;
        }
        """
    )

    if clicked:
        for _ in range(20):
            page.wait_for_timeout(max(250, int(cfg.stable_wait_ms / 2)))
            scroll_to_records_table(page, cfg)

            if not before:
                break

            rows = extract_visible_table_rows(page)
            after = normalize_asset_from_row(rows[0]) if rows else None

            if after and norm(after) != norm(before):
                break

    return bool(clicked)


def find_matching_record(records, asset):
    if asset in records:
        return records[asset]

    asset_norm = norm(asset)

    for key, rec in records.items():
        if norm(key) == asset_norm:
            return rec

    asset_loose = loose_norm(asset)

    for key, rec in records.items():
        if loose_norm(key) == asset_loose:
            return rec

    return None


def harvest_pdf_urls(cfg):
    cfg.ensure_dirs()
    index = load_index(cfg)
    records = index.get("records", {})

    if not records:
        print("[!] No records in index. Run observe first.")
        return

    repaired = repair_invalid_harvest_urls(index)
    if repaired:
        save_index(cfg, index)
        export_urls(cfg, index)
        print(f"[WarRip] Marked {repaired} invalid harvested URLs retryable.")

    print("[WarRip] Page-local PDF URL harvester starting...")
    print("[WarRip] PDF rows → modal → Download → captured /medialink/ufo/*.pdf URL.")

    harvested = 0
    failed = 0
    skipped = 0
    page_num = 1

    with BrowserSession(cfg) as page:
        page.goto(cfg.start_url, wait_until="domcontentloaded", timeout=90000)
        page.wait_for_timeout(4000)
        wait_for_records_ready(page, cfg)

        while page_num <= cfg.max_pages:
            current = active_page_number(page) or page_num
            print(f"\n[WarRip] Harvesting visible page {current}...")

            scroll_to_records_table(page, cfg)
            rows = extract_visible_table_rows(page)

            if not rows:
                save_debug(cfg, page, f"page_{current}", "no_visible_rows")
                print("[!] No visible rows found. Stopping.")
                break

            pdf_rows = [row for row in rows if is_pdf_row(row)]
            skipped_non_pdf_page = len(rows) - len(pdf_rows)
            harvested_page = 0
            failed_page = 0

            print(
                f"[WarRip] Visible rows: {len(rows)} | "
                f"PDF rows: {len(pdf_rows)} | "
                f"skipped non-PDF: {skipped_non_pdf_page}"
            )

            # Copy row list first because DOM changes during modal open/close.
            page_rows = list(rows)

            for local_i, row in enumerate(page_rows, start=1):
                if not is_pdf_row(row):
                    skipped += 1
                    continue

                asset = normalize_asset_from_row(row)

                if not asset:
                    continue

                rec = find_matching_record(records, asset)

                if rec is None:
                    print(f"[{local_i}/{len(page_rows)}] no matching index record: {asset}")
                    continue

                url = rec.get("url") or ""
                if (
                    rec.get("url_source") == "clicked_download_button"
                    and rec.get("confidence") == "high"
                    and is_durable_pdf_url(url)
                ):
                    skipped += 1
                    print(f"[{local_i}/{len(page_rows)}] already good: {asset}")
                    continue

                print(f"[{local_i}/{len(page_rows)}] harvest: {asset}")

                try:
                    # Re-extract rows after every modal close because indices can shift.
                    scroll_to_records_table(page, cfg)
                    fresh_rows = extract_visible_table_rows(page)
                    fresh_match = None

                    for fr in fresh_rows:
                        if norm(normalize_asset_from_row(fr)) == norm(asset):
                            fresh_match = fr
                            break

                    if not fresh_match:
                        raise RuntimeError("fresh row match disappeared before click")

                    click_info = click_row_by_index(page, fresh_match)

                    append_observation(cfg, {
                        "ts": now_iso(),
                        "asset": asset,
                        "kind": "page_local_click_record",
                        "page": current,
                        "click_info": click_info,
                    })

                    if not click_info.get("clicked"):
                        save_debug(cfg, page, asset, "row_not_clicked")
                        raise RuntimeError(f"row not clicked: {click_info}")

                    if not wait_for_modal(page, cfg):
                        save_debug(cfg, page, asset, "modal_not_found")
                        raise RuntimeError("modal did not appear")

                    actual_url, method, candidates = capture_download_url(page, cfg)

                    append_observation(cfg, {
                        "ts": now_iso(),
                        "asset": asset,
                        "kind": "page_local_download_capture",
                        "page": current,
                        "actual_url": actual_url,
                        "method": method,
                        "candidates": candidates,
                    })

                    if not is_durable_pdf_url(actual_url):
                        save_debug(cfg, page, asset, "download_url_not_captured")
                        raise RuntimeError(f"download URL not captured: {method}")

                    mark_harvest_success(rec, actual_url, method, current)

                    harvested += 1
                    harvested_page += 1
                    print(f"    [✓] {method}: {actual_url}")

                    close_modal(page, cfg)
                    scroll_to_records_table(page, cfg)

                except Exception as e:
                    mark_harvest_failure(rec, e, current)
                    failed += 1
                    failed_page += 1
                    log(cfg, f"harvest failed {asset}: {e}")
                    print(f"    [!] failed: {e}")

                    try:
                        close_modal(page, cfg)
                        scroll_to_records_table(page, cfg)
                    except Exception:
                        pass

                save_index(cfg, index)
                export_urls(cfg, index)

            print(
                f"[WarRip] Page {current} PDF summary: "
                f"visible={len(rows)} pdf={len(pdf_rows)} "
                f"skipped_non_pdf={skipped_non_pdf_page} "
                f"harvested={harvested_page} failed={failed_page}"
            )

            if not click_next_page(page, cfg):
                print("[WarRip] No NEXT page. Harvest complete.")
                break

            page_num += 1

    print("\n[✓] URL harvest complete.")
    print(f"Harvested: {harvested}")
    print(f"Skipped:   {skipped}")
    print(f"Failed:    {failed}")


def harvest_real_urls(cfg):
    harvest_pdf_urls(cfg)


def harvest_image_urls(cfg):
    print("[WarRip] Image URL harvester is not implemented yet.")
    print("[WarRip] Use PDF harvest for PDFs only; image handling will be a separate engine.")


def harvest_video_urls(cfg):
    print("[WarRip] Video URL harvester is not implemented yet.")
    print("[WarRip] Videos use browser download/save behavior and need a separate capture engine.")
