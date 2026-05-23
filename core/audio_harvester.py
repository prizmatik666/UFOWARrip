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
from core.index_store import export_path, load_index, save_index
from core.logger import log, now_iso
from core.pagination import maybe_extend_scan_limit
from core.video_harvester import is_hls_video_url, is_preferred_video_capture, scrape_related_media


def export_audio_urls(cfg, index):
    urls = []

    for rec in sorted(index.get("records", {}).values(), key=lambda r: r.get("asset_name", "")):
        audio = rec.get("audio") or {}
        audio_url = audio.get("url")
        if audio_url and is_preferred_audio_capture(audio_url, audio.get("content_type", "")):
            urls.append(audio_url)

    path = export_path(cfg, "harvested_audio_urls")
    path.write_text("\n".join(urls) + ("\n" if urls else ""), encoding="utf-8")
    print(f"[✓] Exported {len(urls)} audio URLs to {path}")


def is_audio_row(row):
    text = (row.get("text") or " ".join(row.get("cells") or "") or "").upper()
    row_type = parsed_row_type(row)

    return "[.AUD]" in text or ".AUD" in text or row_type == ".AUD"


def is_preferred_audio_capture(url, content_type=""):
    return is_preferred_video_capture(url, content_type)


def repair_nonpreferred_audio_urls(index):
    repaired = 0

    for rec in index.get("records", {}).values():
        audio = rec.get("audio") or {}
        url = audio.get("url") or ""

        if not url or is_preferred_audio_capture(url, audio.get("content_type", "")):
            continue

        if is_hls_video_url(url):
            audio["hls_url"] = url

        audio.pop("url", None)
        audio["status"] = "retryable_nonpreferred_audio_url"
        audio["retryable"] = True
        audio["error"] = f"nonpreferred audio URL captured: {url}"
        audio["last_checked_at"] = now_iso()
        rec["audio"] = audio

        events = rec.setdefault("audio_harvest_events", [])
        events.append({
            "ts": now_iso(),
            "status": "failed",
            "error": "nonpreferred audio URL captured",
            "url": url,
        })
        del events[:-25]
        repaired += 1

    return repaired


def wait_for_audio_download_button_ready(page, cfg):
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
                    (
                      text.includes('download audio') ||
                      aria.includes('download audio') ||
                      text.includes('download video') ||
                      aria.includes('download video') ||
                      text === 'download' ||
                      aria === 'download'
                    ) &&
                    !text.includes('image') &&
                    !aria.includes('image') &&
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


def click_download_audio_button(page):
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
                (
                  text.includes('download audio') ||
                  aria.includes('download audio') ||
                  text.includes('download video') ||
                  aria.includes('download video') ||
                  text === 'download' ||
                  aria === 'download'
                ) &&
                !text.includes('image') &&
                !aria.includes('image') &&
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


def get_audio_modal_info(page):
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

          const hasDownloadAudio = buttons.some(b => {
            const blob = `${b.text} ${b.aria}`.toLowerCase();
            return blob.includes('download audio');
          });
          const hasDownloadVideo = buttons.some(b => {
            const blob = `${b.text} ${b.aria}`.toLowerCase();
            return blob.includes('download video');
          });
          const hasMediaPlayer = !!modal.querySelector('video, audio');
          const categoryAudio = lower.includes('audio') || lower.includes('[.aud]') || lower.includes('.aud');

          return {
            is_audio: hasDownloadAudio || hasDownloadVideo || hasMediaPlayer || categoryAudio,
            has_media_player: hasMediaPlayer,
            has_download_audio: hasDownloadAudio,
            has_download_video: hasDownloadVideo,
            category_audio: categoryAudio,
            text: text.slice(0, 2000),
            buttons
          };
        }
        """
    )


def capture_audio_url(page, cfg):
    if not wait_for_audio_download_button_ready(page, cfg):
        return None, "download_audio_button_not_ready", None, ""

    def response_predicate(res):
        try:
            return is_preferred_audio_capture(res.url, res.headers.get("content-type", ""))
        except Exception:
            return False

    def request_predicate(req):
        try:
            return is_preferred_audio_capture(req.url)
        except Exception:
            return False

    try:
        with page.expect_response(response_predicate, timeout=15000) as res_info:
            clicked = click_download_audio_button(page)
            if not clicked:
                return None, "download_audio_button_not_found", None, ""

        response = res_info.value
        return (
            response.url,
            "download_audio_button_network_response",
            response.status,
            response.headers.get("content-type", ""),
        )
    except Exception:
        pass

    try:
        with page.expect_request(request_predicate, timeout=15000) as req_info:
            clicked = click_download_audio_button(page)
            if not clicked:
                return None, "download_audio_button_not_found", None, ""

        request = req_info.value
        return request.url, "download_audio_button_network_request", None, ""
    except Exception:
        pass

    return None, "audio_url_not_captured", None, ""


def save_audio_success(rec, audio_url, source, status, content_type, related_media):
    rec["media_type"] = "audio"
    rec["source_media_tag"] = ".AUD"
    rec["audio"] = {
        "url": audio_url,
        "url_source": source,
        "status": status,
        "content_type": content_type,
        "captured_at": now_iso(),
        "source_media_tag": ".AUD",
        "payload_media_type": "mp4" if urlsplit(audio_url or "").path.lower().endswith(".mp4") else "unknown",
    }

    if related_media:
        rec["related_media"] = related_media

    events = rec.setdefault("audio_harvest_events", [])
    events.append({
        "ts": now_iso(),
        "status": "ok",
        "url": audio_url,
        "source": source,
        "http_status": status,
        "content_type": content_type,
    })
    del events[:-25]


def save_audio_failure(rec, error, related_media=None):
    audio = rec.setdefault("audio", {})
    audio.update({
        "status": "failed",
        "error": str(error),
        "failed_at": now_iso(),
        "retryable": True,
        "source_media_tag": ".AUD",
    })
    rec["source_media_tag"] = ".AUD"

    if related_media:
        rec["related_media"] = related_media

    events = rec.setdefault("audio_harvest_events", [])
    events.append({
        "ts": now_iso(),
        "status": "failed",
        "error": str(error),
    })
    del events[:-25]


def harvest_audio_urls(cfg):
    cfg.ensure_dirs()
    index = load_index(cfg)
    records = index.get("records", {})

    if not records:
        print("[!] No records in index. Run observe first.")
        return

    repaired = repair_nonpreferred_audio_urls(index)
    if repaired:
        save_index(cfg, index)
        export_audio_urls(cfg, index)
        print(f"[WarRip] Marked {repaired} non-MP4 audio captures retryable.")

    print("[WarRip] Page-local audio URL harvester starting...")
    print("[WarRip] Audio rows [.AUD] -> modal -> Download -> captured MP4 media URL.")

    captured = 0
    skipped = 0
    failed = 0
    page_num = 1
    scan_limit = cfg.max_pages

    with BrowserSession(cfg) as page:
        page.goto(cfg.start_url, wait_until="domcontentloaded", timeout=90000)
        page.wait_for_timeout(4000)
        wait_for_records_ready(page, cfg)

        while page_num <= scan_limit:
            current = active_page_number(page) or page_num
            print(f"\n[WarRip] Audio harvest page {current}...")

            scroll_to_records_table(page, cfg)
            rows = extract_visible_table_rows(page)

            if not rows:
                save_debug(cfg, page, f"audio_page_{current}", "no_visible_rows")
                print("[!] No visible rows found. Stopping.")
                break

            audio_rows = [row for row in rows if is_audio_row(row)]
            skipped_non_audio_page = len(rows) - len(audio_rows)
            captured_page = 0

            print(
                f"[WarRip] Visible rows: {len(rows)} | "
                f"audio rows: {len(audio_rows)} | "
                f"skipped non-audio: {skipped_non_audio_page}"
            )

            page_rows = list(rows)

            for local_i, row in enumerate(page_rows, start=1):
                asset = normalize_asset_from_row(row)
                if not asset:
                    continue

                if not is_audio_row(row):
                    skipped += 1
                    continue

                rec = find_matching_record(records, asset)
                if rec is None:
                    print(f"[{local_i}/{len(page_rows)}] no matching index record: {asset}")
                    continue

                rec["source_media_tag"] = ".AUD"
                audio = rec.get("audio") or {}
                existing_audio_url = audio.get("url")
                if existing_audio_url and is_preferred_audio_capture(existing_audio_url, audio.get("content_type", "")):
                    skipped += 1
                    print(f"[{local_i}/{len(page_rows)}] already has audio URL: {asset}")
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

                    print(f"[{local_i}/{len(page_rows)}] inspect audio: {asset}")
                    click_info = click_row_by_index(page, fresh_match)
                    append_observation(cfg, {
                        "ts": now_iso(),
                        "asset": asset,
                        "kind": "audio_click_record",
                        "page": current,
                        "click_info": click_info,
                    })

                    if not click_info.get("clicked"):
                        save_debug(cfg, page, asset, "audio_row_not_clicked")
                        raise RuntimeError(f"row not clicked: {click_info}")

                    if not wait_for_modal(page, cfg):
                        save_debug(cfg, page, asset, "audio_modal_not_found")
                        raise RuntimeError("modal did not appear")

                    modal_info = get_audio_modal_info(page)
                    related_media = scrape_related_media(page)
                    append_observation(cfg, {
                        "ts": now_iso(),
                        "asset": asset,
                        "kind": "audio_modal_inspect",
                        "page": current,
                        "modal_info": modal_info,
                        "related_media": related_media,
                    })

                    if related_media:
                        rec["related_media"] = related_media

                    if not modal_info.get("is_audio"):
                        skipped += 1
                        print("    [-] not audio")
                        close_modal(page, cfg)
                        scroll_to_records_table(page, cfg)
                        save_index(cfg, index)
                        export_audio_urls(cfg, index)
                        continue

                    audio_url, source, status, content_type = capture_audio_url(page, cfg)
                    append_observation(cfg, {
                        "ts": now_iso(),
                        "asset": asset,
                        "kind": "audio_download_capture",
                        "page": current,
                        "audio_url": audio_url,
                        "source": source,
                        "status": status,
                        "content_type": content_type,
                    })

                    if not audio_url:
                        save_debug(cfg, page, asset, "audio_url_not_captured")
                        raise RuntimeError(f"audio URL not captured: {source}")

                    if not is_preferred_audio_capture(audio_url, content_type):
                        save_debug(cfg, page, asset, "audio_url_nonpreferred")
                        raise RuntimeError(f"nonpreferred audio URL captured: {audio_url}")

                    save_audio_success(rec, audio_url, source, status, content_type, related_media)
                    captured += 1
                    captured_page += 1
                    print(f"    [✓] {source}: {audio_url}")

                    close_modal(page, cfg)
                    scroll_to_records_table(page, cfg)

                except Exception as e:
                    save_audio_failure(rec, e)
                    failed += 1
                    log(cfg, f"audio harvest failed {asset}: {e}")
                    print(f"    [!] failed: {e}")

                    try:
                        close_modal(page, cfg)
                        scroll_to_records_table(page, cfg)
                    except Exception:
                        pass

                save_index(cfg, index)
                export_audio_urls(cfg, index)

            print(
                f"[WarRip] Page {current} audio summary: "
                f"visible={len(rows)} audio={len(audio_rows)} "
                f"skipped_non_audio={skipped_non_audio_page} harvested={captured_page}"
            )

            next_page = page_num + 1
            scan_limit, should_continue = maybe_extend_scan_limit(cfg, page, page_num, next_page, scan_limit)
            if not should_continue:
                break

            if not click_next_page(page, cfg):
                print("[WarRip] No NEXT page. Audio harvest complete.")
                break

            page_num += 1

    print("\n[✓] Audio URL harvest complete.")
    print(f"Captured: {captured}")
    print(f"Skipped:  {skipped}")
    print(f"Failed:   {failed}")
