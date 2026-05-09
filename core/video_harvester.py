# UFOWARrip
# Created by Prizmatik
# https://github.com/prizmatik666/UFOWARrip

import json
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
    save_debug,
    scroll_to_records_table,
    wait_for_modal,
    wait_for_records_ready,
)
from core.index_store import load_index, save_index
from core.logger import log, now_iso


def export_video_urls(cfg, index):
    urls = []

    for rec in sorted(index.get("records", {}).values(), key=lambda r: r.get("asset_name", "")):
        video = rec.get("video") or {}
        video_url = video.get("url")
        if video_url and is_preferred_video_capture(video_url, video.get("content_type", "")):
            urls.append(video_url)

    path = cfg.data_dir / "video_urls.txt"
    path.write_text("\n".join(urls) + ("\n" if urls else ""), encoding="utf-8")
    print(f"[✓] Exported {len(urls)} video URLs to {path}")


def parsed_row_type(row):
    cells = row.get("cells") or []

    for cell in reversed(cells):
        value = (cell or "").strip().upper()
        if value.startswith("[.") and value.endswith("]"):
            return value.strip("[]")
        if value.startswith(".") and len(value) <= 8:
            return value

    return ""


def is_video_row(row):
    text = (row.get("text") or " ".join(row.get("cells") or "") or "").upper()
    row_type = parsed_row_type(row)

    return "[.VID]" in text or ".VID" in text or row_type == ".VID"


def is_preferred_video_capture(url, content_type=""):
    low_url = (url or "").lower()
    path = urlsplit(url or "").path.lower()

    if low_url.startswith("blob:"):
        return False

    if path.endswith(".mp4"):
        return True

    return False


def is_hls_video_url(url):
    low_url = (url or "").lower()
    return ".m3u8" in low_url or ".ts" in low_url or ".mp2t" in low_url


def repair_nonpreferred_video_urls(index):
    repaired = 0

    for rec in index.get("records", {}).values():
        video = rec.get("video") or {}
        url = video.get("url") or ""

        if not url or is_preferred_video_capture(url, video.get("content_type", "")):
            continue

        if is_hls_video_url(url):
            video["hls_url"] = url

        video.pop("url", None)
        video["status"] = "retryable_nonpreferred_video_url"
        video["retryable"] = True
        video["error"] = f"nonpreferred video URL captured: {url}"
        video["last_checked_at"] = now_iso()
        rec["video"] = video

        events = rec.setdefault("video_harvest_events", [])
        events.append({
            "ts": now_iso(),
            "status": "failed",
            "error": "nonpreferred video URL captured",
            "url": url,
        })
        del events[:-25]
        repaired += 1

    return repaired


def wait_for_video_download_button_ready(page, cfg):
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
                    (text.includes('download video') || aria.includes('download video')) &&
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


def click_download_video_button(page):
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
                (text.includes('download video') || aria.includes('download video')) &&
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


def get_video_modal_info(page):
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

          const hasVideoPlayer = !!modal.querySelector('video#record-video-player, video');
          const hasDownloadVideo = buttons.some(b => {
            const blob = `${b.text} ${b.aria}`.toLowerCase();
            return blob.includes('download video');
          });
          const categoryBroll = /category\\s*[:\\n ]+b-roll/i.test(text) || lower.includes('b-roll');
          const hasLength = /length\\s*[:\\n ]+/i.test(text) || lower.includes('length');

          return {
            is_video: hasVideoPlayer || hasDownloadVideo || categoryBroll || (hasLength && lower.includes('download video')),
            has_video_player: hasVideoPlayer,
            has_download_video: hasDownloadVideo,
            category_broll: categoryBroll,
            has_length: hasLength,
            text: text.slice(0, 2000),
            buttons
          };
        }
        """
    )


def scrape_related_media(page):
    return page.evaluate(
        """
        () => {
          const containers = [
            ...document.querySelectorAll('div.record-related-media[data-record-related-media]'),
            ...document.querySelectorAll('[data-record-related-media]'),
            ...document.querySelectorAll('.record-related-media')
          ];

          const seen = new Set();
          const out = [];

          for (const container of containers) {
            for (const a of container.querySelectorAll('a[href]')) {
              const href = a.href || a.getAttribute('href') || '';
              if (!href || seen.has(href)) continue;
              seen.add(href);

              const path = new URL(href, document.location.href).pathname.toLowerCase();
              let type = 'unknown';
              if (path.endsWith('.pdf')) type = 'pdf';
              else if (path.endsWith('.mp4') || path.endsWith('.mov') || path.endsWith('.webm')) type = 'video';
              else if (path.endsWith('.png') || path.endsWith('.jpg') || path.endsWith('.jpeg') || path.endsWith('.webp')) type = 'image';

              out.push({
                label: (a.innerText || a.textContent || '').trim(),
                url: href,
                type,
                source: 'modal_related_media'
              });
            }
          }

          return out;
        }
        """
    )


def capture_video_url(page, cfg):
    if not wait_for_video_download_button_ready(page, cfg):
        return None, "download_video_button_not_ready", None, ""

    def response_predicate(res):
        try:
            return is_preferred_video_capture(res.url, res.headers.get("content-type", ""))
        except Exception:
            return False

    def request_predicate(req):
        try:
            return is_preferred_video_capture(req.url)
        except Exception:
            return False

    try:
        with page.expect_response(response_predicate, timeout=15000) as res_info:
            clicked = click_download_video_button(page)
            if not clicked:
                return None, "download_video_button_not_found", None, ""

        response = res_info.value
        return (
            response.url,
            "download_video_button_network_response",
            response.status,
            response.headers.get("content-type", ""),
        )
    except Exception:
        pass

    try:
        with page.expect_request(request_predicate, timeout=15000) as req_info:
            clicked = click_download_video_button(page)
            if not clicked:
                return None, "download_video_button_not_found", None, ""

        request = req_info.value
        return request.url, "download_video_button_network_request", None, ""
    except Exception:
        pass

    return None, "video_url_not_captured", None, ""


def save_video_success(rec, video_url, source, status, content_type, related_media):
    rec["media_type"] = "video"
    rec["video"] = {
        "url": video_url,
        "url_source": source,
        "status": status,
        "content_type": content_type,
        "captured_at": now_iso(),
    }

    if related_media:
        rec["related_media"] = related_media

    events = rec.setdefault("video_harvest_events", [])
    events.append({
        "ts": now_iso(),
        "status": "ok",
        "url": video_url,
        "source": source,
        "http_status": status,
        "content_type": content_type,
    })
    del events[:-25]


def save_video_failure(rec, error, related_media=None):
    video = rec.setdefault("video", {})
    video.update({
        "status": "failed",
        "error": str(error),
        "failed_at": now_iso(),
        "retryable": True,
    })

    if related_media:
        rec["related_media"] = related_media

    events = rec.setdefault("video_harvest_events", [])
    events.append({
        "ts": now_iso(),
        "status": "failed",
        "error": str(error),
    })
    del events[:-25]


def harvest_video_urls(cfg):
    cfg.ensure_dirs()
    index = load_index(cfg)
    records = index.get("records", {})

    if not records:
        print("[!] No records in index. Run observe first.")
        return

    repaired = repair_nonpreferred_video_urls(index)
    if repaired:
        save_index(cfg, index)
        export_video_urls(cfg, index)
        print(f"[WarRip] Marked {repaired} non-MP4 video captures retryable.")

    print("[WarRip] Page-local video URL harvester starting...")
    print("[WarRip] Video rows → modal → Download Video → captured MP4 network URL.")

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
            print(f"\n[WarRip] Video harvest page {current}...")

            scroll_to_records_table(page, cfg)
            rows = extract_visible_table_rows(page)

            if not rows:
                save_debug(cfg, page, f"video_page_{current}", "no_visible_rows")
                print("[!] No visible rows found. Stopping.")
                break

            video_rows = [row for row in rows if is_video_row(row)]
            skipped_non_video_page = len(rows) - len(video_rows)
            captured_page = 0

            print(
                f"[WarRip] Visible rows: {len(rows)} | "
                f"video rows: {len(video_rows)} | "
                f"skipped non-video: {skipped_non_video_page}"
            )
            page_rows = list(rows)

            for local_i, row in enumerate(page_rows, start=1):
                asset = normalize_asset_from_row(row)
                if not asset:
                    continue

                if not is_video_row(row):
                    skipped += 1
                    continue

                rec = find_matching_record(records, asset)
                if rec is None:
                    print(f"[{local_i}/{len(page_rows)}] no matching index record: {asset}")
                    continue

                video = rec.get("video") or {}
                existing_video_url = video.get("url")
                if existing_video_url and is_preferred_video_capture(existing_video_url, video.get("content_type", "")):
                    skipped += 1
                    print(f"[{local_i}/{len(page_rows)}] already has video URL: {asset}")
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

                    print(f"[{local_i}/{len(page_rows)}] inspect video: {asset}")
                    click_info = click_row_by_index(page, fresh_match)
                    append_observation(cfg, {
                        "ts": now_iso(),
                        "asset": asset,
                        "kind": "video_click_record",
                        "page": current,
                        "click_info": click_info,
                    })

                    if not click_info.get("clicked"):
                        save_debug(cfg, page, asset, "video_row_not_clicked")
                        raise RuntimeError(f"row not clicked: {click_info}")

                    if not wait_for_modal(page, cfg):
                        save_debug(cfg, page, asset, "video_modal_not_found")
                        raise RuntimeError("modal did not appear")

                    modal_info = get_video_modal_info(page)
                    related_media = scrape_related_media(page)
                    append_observation(cfg, {
                        "ts": now_iso(),
                        "asset": asset,
                        "kind": "video_modal_inspect",
                        "page": current,
                        "modal_info": modal_info,
                        "related_media": related_media,
                    })

                    if related_media:
                        rec["related_media"] = related_media

                    if not modal_info.get("is_video"):
                        skipped += 1
                        print(f"    [-] not video")
                        close_modal(page, cfg)
                        scroll_to_records_table(page, cfg)
                        save_index(cfg, index)
                        export_video_urls(cfg, index)
                        continue

                    video_url, source, status, content_type = capture_video_url(page, cfg)
                    append_observation(cfg, {
                        "ts": now_iso(),
                        "asset": asset,
                        "kind": "video_download_capture",
                        "page": current,
                        "video_url": video_url,
                        "source": source,
                        "status": status,
                        "content_type": content_type,
                    })

                    if not video_url:
                        save_debug(cfg, page, asset, "video_url_not_captured")
                        raise RuntimeError(f"video URL not captured: {source}")

                    save_video_success(rec, video_url, source, status, content_type, related_media)
                    captured += 1
                    captured_page += 1
                    print(f"    [✓] {source}: {video_url}")

                    close_modal(page, cfg)
                    scroll_to_records_table(page, cfg)

                except Exception as e:
                    save_video_failure(rec, e)
                    failed += 1
                    log(cfg, f"video harvest failed {asset}: {e}")
                    print(f"    [!] failed: {e}")

                    try:
                        close_modal(page, cfg)
                        scroll_to_records_table(page, cfg)
                    except Exception:
                        pass

                save_index(cfg, index)
                export_video_urls(cfg, index)

            print(
                f"[WarRip] Page {current} video summary: "
                f"visible={len(rows)} video={len(video_rows)} "
                f"skipped_non_video={skipped_non_video_page} harvested={captured_page}"
            )

            if not click_next_page(page, cfg):
                print("[WarRip] No NEXT page. Video harvest complete.")
                break

            page_num += 1

    print("\n[✓] Video URL harvest complete.")
    print(f"Captured: {captured}")
    print(f"Skipped:  {skipped}")
    print(f"Failed:   {failed}")
