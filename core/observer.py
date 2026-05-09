# UFOWARrip
# Created by Prizmatik
# https://github.com/prizmatik666/UFOWARrip

import json
import time
from core.browser_session import BrowserSession
from core.extractor import extract_visible_records, active_page_number
from core.index_store import load_index, save_index, merge_record, export_urls
from core.logger import log, now_iso


def save_debug_snapshot(cfg, page, label):
    cfg.ensure_dirs()
    safe = label.replace(" ", "_")
    page.screenshot(path=str(cfg.debug_dir / "screenshots" / f"{safe}.png"), full_page=True)
    (cfg.debug_dir / "html" / f"{safe}.html").write_text(page.content(), encoding="utf-8", errors="replace")
    text = page.evaluate("() => document.body ? document.body.innerText : ''")
    (cfg.debug_dir / "text" / f"{safe}.txt").write_text(text or "", encoding="utf-8", errors="replace")


def append_network_event(cfg, data):
    cfg.ensure_dirs()
    path = cfg.data_dir / "network_events.jsonl"
    path.open("a", encoding="utf-8").write(json.dumps(data, sort_keys=True) + "\n")


def install_network_observer(cfg, page):
    def on_response(response):
        try:
            url = response.url
            ct = response.headers.get("content-type", "")
            interesting = any(x in url.lower() for x in [".pdf", ".csv", "ufo", "medialink"]) or any(
                x in ct.lower() for x in ["pdf", "csv", "json", "text"]
            )

            if interesting:
                append_network_event(cfg, {
                    "ts": now_iso(),
                    "url": url,
                    "status": response.status,
                    "content_type": ct,
                    "method": response.request.method,
                    "resource_type": response.request.resource_type,
                })
        except Exception as e:
            log(cfg, f"network observer error: {e}")

    page.on("response", on_response)


def wait_for_table_stable(cfg, page):
    last = None
    stable_hits = 0

    for _ in range(20):
        txt = page.evaluate(
            """
            () => [...document.querySelectorAll('body *')]
              .map(e => e.innerText || '')
              .filter(t => /65_/i.test(t))
              .join('\\n')
            """
        )

        if txt and txt == last:
            stable_hits += 1
        else:
            stable_hits = 0

        if txt and stable_hits >= 2:
            return True

        last = txt
        page.wait_for_timeout(cfg.stable_wait_ms)

    return False


def click_page_number(page, target):
    return page.evaluate(
        """
        (target) => {
          const buttons = [...document.querySelectorAll('button.pagination-button')]
            .filter(b => (b.innerText || '').trim() === String(target));

          if (!buttons.length) return false;

          buttons[0].scrollIntoView({block: 'center'});
          buttons[0].click();
          return true;
        }
        """,
        target,
    )


def observe_site(cfg):
    cfg.ensure_dirs()
    log(cfg, "observe_site start")

    index = load_index(cfg)

    with BrowserSession(cfg) as page:
        install_network_observer(cfg, page)

        print("[WarRip] Opening site...")
        page.goto(cfg.start_url, wait_until="domcontentloaded", timeout=90000)
        page.wait_for_timeout(4000)

        page_num = active_page_number(page) or 1
        previous_assets = set()

        while page_num <= cfg.max_pages:
            print(f"[WarRip] Observing page {page_num}...")

            wait_for_table_stable(cfg, page)
            save_debug_snapshot(cfg, page, f"page_{page_num}")

            records = extract_visible_records(page, cfg, page_num)
            current_assets = {r["asset_name"] for r in records}

            if page_num > 1 and current_assets and current_assets == previous_assets:
                print("[!] Page did not change records. Stopping loop guard.")
                break

            for rec in records:
                merge_record(index, rec)

            save_index(cfg, index)
            export_urls(cfg, index)

            print(f"[+] Page {page_num}: {len(records)} records | total: {len(index.get('records', {}))}")
            log(cfg, f"page={page_num} records={len(records)}")

            previous_assets = current_assets
            next_page = page_num + 1

            if not click_page_number(page, next_page):
                print("[WarRip] No next numeric page button. Observation complete.")
                break

            page.wait_for_timeout(cfg.stable_wait_ms)
            page_num = next_page

    print("[✓] Observation complete.")
