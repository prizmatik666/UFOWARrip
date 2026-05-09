# UFOWARrip
# Created by Prizmatik
# https://github.com/prizmatik666/UFOWARrip

from urllib.parse import urlsplit

from core.browser_session import BrowserSession
from core.harvester import (
    active_page_number,
    append_observation,
    click_next_page,
    click_row_by_index,
    close_modal,
    extract_visible_table_rows,
    find_matching_record,
    norm,
    normalize_asset_from_row,
    parsed_row_type,
    save_debug,
    scroll_to_records_table,
    wait_for_modal,
    wait_for_records_ready,
)
from core.index_store import load_index, save_index
from core.logger import log, now_iso


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}


def export_image_urls(cfg, index):
    urls = []

    for rec in sorted(index.get("records", {}).values(), key=lambda r: r.get("asset_name", "")):
        image = rec.get("image") or {}
        image_url = image.get("url")
        if image_url and is_preferred_image_capture(image_url, image.get("content_type", "")):
            urls.append(image_url)

    path = cfg.data_dir / "image_urls.txt"
    path.write_text("\n".join(urls) + ("\n" if urls else ""), encoding="utf-8")
    print(f"[✓] Exported {len(urls)} image URLs to {path}")


def is_image_row(row):
    text = (row.get("text") or " ".join(row.get("cells") or "") or "").upper()
    row_type = parsed_row_type(row)

    return "[.IMG]" in text or ".IMG" in text or row_type == ".IMG"


def is_preferred_image_capture(url, content_type=""):
    low_url = (url or "").lower()
    low_ct = (content_type or "").lower()
    path = urlsplit(url or "").path.lower()

    if low_url.startswith("blob:"):
        return False

    if any(path.endswith(ext) for ext in IMAGE_EXTENSIONS):
        return True

    return low_ct.startswith("image/")


def wait_for_image_download_button_ready(page, cfg):
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
                '#record-modal',
                '.record-modal',
                '[role="dialog"]',
                '[aria-modal="true"]'
              ].flatMap(sel => [...document.querySelectorAll(sel)].filter(visible));

              for (const scope of (scopes.length ? scopes : [document.body])) {
                const buttons = [...scope.querySelectorAll('button, a')].filter(visible);
                for (const el of buttons) {
                  const text = (el.innerText || '').trim().toLowerCase();
                  const aria = (el.getAttribute('aria-label') || '').toLowerCase();

                  if (
                    (text.includes('download image') || text === 'download' || aria.includes('download')) &&
                    !text.includes('video') &&
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


def click_download_image_button(page):
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

          const scopes = [
            '#record-modal',
            '.record-modal',
            '[role="dialog"]',
            '[aria-modal="true"]'
          ].flatMap(sel => [...document.querySelectorAll(sel)].filter(visible));

          for (const scope of (scopes.length ? scopes : [document.body])) {
            const buttons = [...scope.querySelectorAll('button, a')].filter(visible);
            for (const el of buttons) {
              const text = (el.innerText || '').trim().toLowerCase();
              const aria = (el.getAttribute('aria-label') || '').toLowerCase();

              if (
                (text.includes('download image') || text === 'download' || aria.includes('download')) &&
                !text.includes('video') &&
                !el.disabled &&
                el.getAttribute('aria-disabled') !== 'true'
              ) {
                el.scrollIntoView({block:'center', inline:'center'});
                el.click();
                return true;
              }
            }
          }

          return false;
        }
        """
    )


def get_image_modal_info(page):
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

          const modal = [
            document.querySelector('#record-modal'),
            document.querySelector('.record-modal'),
            document.querySelector('[role="dialog"]'),
            document.querySelector('[aria-modal="true"]')
          ].find(el => el && visible(el)) || document.body;

          const text = modal.innerText || '';
          const lower = text.toLowerCase();
          const buttons = [...modal.querySelectorAll('button, a')]
            .filter(visible)
            .map(el => ({
              text: (el.innerText || '').trim(),
              aria: el.getAttribute('aria-label') || '',
              href: el.href || el.getAttribute('href') || ''
            }));

          const hasImage = !!modal.querySelector('img');
          const hasDownloadImage = buttons.some(b => {
            const blob = `${b.text} ${b.aria}`.toLowerCase();
            return blob.includes('download image');
          });
          const categoryImage = lower.includes('image') || lower.includes('photo');

          return {
            is_image: hasImage || hasDownloadImage || categoryImage,
            has_image: hasImage,
            has_download_image: hasDownloadImage,
            category_image: categoryImage,
            text: text.slice(0, 2000),
            buttons
          };
        }
        """
    )


def scrape_image_urls_from_modal(page):
    return page.evaluate(
        """
        () => {
          const modal = [
            document.querySelector('#record-modal'),
            document.querySelector('.record-modal'),
            document.querySelector('[role="dialog"]'),
            document.querySelector('[aria-modal="true"]')
          ].find(Boolean) || document.body;

          const urls = [];
          for (const img of modal.querySelectorAll('img[src]')) {
            const src = img.src || img.getAttribute('src') || '';
            if (src) urls.push(src);
          }
          for (const a of modal.querySelectorAll('a[href]')) {
            const href = a.href || a.getAttribute('href') || '';
            if (href) urls.push(href);
          }
          return [...new Set(urls)];
        }
        """
    )


def capture_image_url(page, cfg):
    if not wait_for_image_download_button_ready(page, cfg):
        for url in scrape_image_urls_from_modal(page):
            if is_preferred_image_capture(url):
                return url, "modal_image_src", None, ""
        return None, "download_image_button_not_ready", None, ""

    def response_predicate(res):
        try:
            return is_preferred_image_capture(res.url, res.headers.get("content-type", ""))
        except Exception:
            return False

    def request_predicate(req):
        try:
            return is_preferred_image_capture(req.url)
        except Exception:
            return False

    try:
        with page.context.expect_page(timeout=10000) as new_page_info:
            clicked = click_download_image_button(page)
            if not clicked:
                return None, "download_image_button_not_found", None, ""

        new_page = new_page_info.value
        for _ in range(30):
            url = new_page.url or ""
            if is_preferred_image_capture(url):
                try:
                    new_page.close()
                except Exception:
                    pass
                return url, "download_image_button_new_page", None, ""
            new_page.wait_for_timeout(300)

        try:
            new_page.close()
        except Exception:
            pass
    except Exception:
        pass

    try:
        with page.expect_response(response_predicate, timeout=10000) as res_info:
            clicked = click_download_image_button(page)
            if not clicked:
                return None, "download_image_button_not_found", None, ""

        response = res_info.value
        return (
            response.url,
            "download_image_button_network_response",
            response.status,
            response.headers.get("content-type", ""),
        )
    except Exception:
        pass

    try:
        with page.expect_request(request_predicate, timeout=10000) as req_info:
            clicked = click_download_image_button(page)
            if not clicked:
                return None, "download_image_button_not_found", None, ""

        request = req_info.value
        return request.url, "download_image_button_network_request", None, ""
    except Exception:
        pass

    for url in scrape_image_urls_from_modal(page):
        if is_preferred_image_capture(url):
            return url, "modal_image_src", None, ""

    return None, "image_url_not_captured", None, ""


def save_image_success(rec, image_url, source, status, content_type):
    rec["media_type"] = "image"
    rec["image"] = {
        "url": image_url,
        "url_source": source,
        "status": status,
        "content_type": content_type,
        "captured_at": now_iso(),
    }

    events = rec.setdefault("image_harvest_events", [])
    events.append({
        "ts": now_iso(),
        "status": "ok",
        "url": image_url,
        "source": source,
        "http_status": status,
        "content_type": content_type,
    })
    del events[:-25]


def save_image_failure(rec, error):
    image = rec.setdefault("image", {})
    image.update({
        "status": "failed",
        "error": str(error),
        "failed_at": now_iso(),
        "retryable": True,
    })

    events = rec.setdefault("image_harvest_events", [])
    events.append({
        "ts": now_iso(),
        "status": "failed",
        "error": str(error),
    })
    del events[:-25]


def harvest_image_urls(cfg):
    cfg.ensure_dirs()
    index = load_index(cfg)
    records = index.get("records", {})

    if not records:
        print("[!] No records in index. Run observe first.")
        return

    print("[WarRip] Page-local image URL harvester starting...")
    print("[WarRip] Image rows → modal → Download Image → captured image URL.")

    captured = 0
    skipped = 0
    failed = 0
    page_num = 1

    with BrowserSession(cfg) as page:
        page.goto(cfg.start_url, wait_until="domcontentloaded", timeout=90000)
        page.wait_for_timeout(4000)
        wait_for_records_ready(page, cfg)

        while page_num <= cfg.max_pages:
            current = active_page_number(page) or page_num
            print(f"\n[WarRip] Image harvest page {current}...")

            scroll_to_records_table(page, cfg)
            rows = extract_visible_table_rows(page)

            if not rows:
                save_debug(cfg, page, f"image_page_{current}", "no_visible_rows")
                print("[!] No visible rows found. Stopping.")
                break

            image_rows = [row for row in rows if is_image_row(row)]
            skipped_non_image_page = len(rows) - len(image_rows)
            captured_page = 0
            failed_page = 0

            print(
                f"[WarRip] Visible rows: {len(rows)} | "
                f"image rows: {len(image_rows)} | "
                f"skipped non-image: {skipped_non_image_page}"
            )

            for local_i, row in enumerate(list(rows), start=1):
                if not is_image_row(row):
                    skipped += 1
                    continue

                asset = normalize_asset_from_row(row)
                if not asset:
                    continue

                rec = find_matching_record(records, asset)
                if rec is None:
                    print(f"[{local_i}/{len(rows)}] no matching index record: {asset}")
                    continue

                image = rec.get("image") or {}
                existing_image_url = image.get("url")
                if existing_image_url and is_preferred_image_capture(existing_image_url, image.get("content_type", "")):
                    skipped += 1
                    print(f"[{local_i}/{len(rows)}] already has image URL: {asset}")
                    continue

                try:
                    scroll_to_records_table(page, cfg)
                    fresh_rows = extract_visible_table_rows(page)
                    fresh_match = None

                    for fr in fresh_rows:
                        if norm(normalize_asset_from_row(fr)) == norm(asset):
                            fresh_match = fr
                            break

                    if not fresh_match:
                        raise RuntimeError("fresh row match disappeared before click")

                    print(f"[{local_i}/{len(rows)}] inspect image: {asset}")
                    click_info = click_row_by_index(page, fresh_match)
                    append_observation(cfg, {
                        "ts": now_iso(),
                        "asset": asset,
                        "kind": "image_click_record",
                        "page": current,
                        "click_info": click_info,
                    })

                    if not click_info.get("clicked"):
                        save_debug(cfg, page, asset, "image_row_not_clicked")
                        raise RuntimeError(f"row not clicked: {click_info}")

                    if not wait_for_modal(page, cfg):
                        save_debug(cfg, page, asset, "image_modal_not_found")
                        raise RuntimeError("modal did not appear")

                    modal_info = get_image_modal_info(page)
                    append_observation(cfg, {
                        "ts": now_iso(),
                        "asset": asset,
                        "kind": "image_modal_inspect",
                        "page": current,
                        "modal_info": modal_info,
                    })

                    if not modal_info.get("is_image"):
                        skipped += 1
                        print("    [-] not image")
                        close_modal(page, cfg)
                        scroll_to_records_table(page, cfg)
                        save_index(cfg, index)
                        export_image_urls(cfg, index)
                        continue

                    image_url, source, status, content_type = capture_image_url(page, cfg)
                    append_observation(cfg, {
                        "ts": now_iso(),
                        "asset": asset,
                        "kind": "image_download_capture",
                        "page": current,
                        "image_url": image_url,
                        "source": source,
                        "status": status,
                        "content_type": content_type,
                    })

                    if not image_url or not is_preferred_image_capture(image_url, content_type):
                        save_debug(cfg, page, asset, "image_url_not_captured")
                        raise RuntimeError(f"image URL not captured: {source}")

                    save_image_success(rec, image_url, source, status, content_type)
                    captured += 1
                    captured_page += 1
                    print(f"    [✓] {source}: {image_url}")

                    close_modal(page, cfg)
                    scroll_to_records_table(page, cfg)

                except Exception as e:
                    save_image_failure(rec, e)
                    failed += 1
                    failed_page += 1
                    log(cfg, f"image harvest failed {asset}: {e}")
                    print(f"    [!] failed: {e}")

                    try:
                        close_modal(page, cfg)
                        scroll_to_records_table(page, cfg)
                    except Exception:
                        pass

                save_index(cfg, index)
                export_image_urls(cfg, index)

            print(
                f"[WarRip] Page {current} image summary: "
                f"visible={len(rows)} image={len(image_rows)} "
                f"skipped_non_image={skipped_non_image_page} "
                f"harvested={captured_page} failed={failed_page}"
            )

            if not click_next_page(page, cfg):
                print("[WarRip] No NEXT page. Image harvest complete.")
                break

            page_num += 1

    print("\n[✓] Image URL harvest complete.")
    print(f"Captured: {captured}")
    print(f"Skipped:  {skipped}")
    print(f"Failed:   {failed}")
