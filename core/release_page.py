# UFOWARrip
# Created by Prizmatik
# https://github.com/prizmatik666/UFOWARrip

from core.config import BASE_UFO_URL


def release_key(cfg):
    return f"{int(cfg.release_number):02d}"


def active_release_tab(page):
    return page.evaluate(
        """
        () => {
          const active =
            document.querySelector('.release-tab.active') ||
            document.querySelector('[role="tab"][aria-selected="true"]');

          if (!active) return null;

          return {
            release: active.dataset.release || active.getAttribute('data-release') || null,
            id: active.id || '',
            ariaSelected: active.getAttribute('aria-selected') || '',
            classes: String(active.className || ''),
            controls: active.getAttribute('aria-controls') || ''
          };
        }
        """
    )


def select_release_tab(page, cfg):
    key = release_key(cfg)
    selector = f'#release-tab-{key}, button[data-release="{key}"]'

    print(f"[WarRip] Requested release: {key}")
    page.wait_for_selector(selector, timeout=15000)
    page.click(selector)

    page.wait_for_function(
        """
        (releaseKey) => {
          const tab =
            document.querySelector(`#release-tab-${releaseKey}`) ||
            document.querySelector(`button[data-release="${releaseKey}"]`);

          if (!tab) return false;

          const active =
            tab.classList.contains('active') ||
            tab.getAttribute('aria-selected') === 'true';

          const panelId = tab.getAttribute('aria-controls') || `release-panel-${releaseKey}`;
          const panel = document.getElementById(panelId);
          const panelActive =
            !panel ||
            panel.classList.contains('active') ||
            panel.getAttribute('aria-hidden') === 'false' ||
            panel.offsetParent !== null;

          return active && panelActive;
        }
        """,
        arg=key,
        timeout=15000,
    )

    active = active_release_tab(page) or {}
    active_key = active.get("release")
    print(f"[WarRip] Active release tab after click: {active_key}")

    if active_key != key:
        raise RuntimeError(f"Release tab mismatch: expected {key}, got {active_key}")

    print(f"[WarRip] Harvest scope: release_{key} only")
    return active


def visible_record_release_tags(page):
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

          const recordSelectors = [
            '#recordList .record-row',
            '.record-list .record-row',
            '[data-record-trigger]',
            '#releaseTable2026 tbody tr',
            '.dataTables_wrapper tbody tr'
          ].join(',');

          const records = [...document.querySelectorAll(recordSelectors)].filter(visible);
          const out = [];

          for (const record of records) {
            const tagged = [
              record,
              ...record.querySelectorAll('[data-release], [data-release-link], [data-record-release]')
            ];

            const tags = [...new Set(tagged.map(el =>
              el.dataset.release ||
              el.dataset.releaseLink ||
              el.dataset.recordRelease ||
              el.getAttribute('data-release') ||
              el.getAttribute('data-release-link') ||
              el.getAttribute('data-record-release') ||
              ''
            ).filter(Boolean))];

            const links = [...record.querySelectorAll('a[href]')]
              .map(a => ({
                text: (a.innerText || a.textContent || '').trim().slice(0, 120),
                dataRelease: a.dataset.release || a.dataset.releaseLink || '',
                href: a.href || a.getAttribute('href') || ''
              }))
              .filter(a => a.dataRelease);

            out.push({
              text: (record.innerText || '').trim().slice(0, 200),
              tags,
              links
            });
          }

          return out;
        }
        """
    )


def validate_release_scope(page, cfg, *, require_rows=False):
    key = release_key(cfg)
    active = active_release_tab(page) or {}
    active_key = active.get("release")

    if active_key != key:
        raise RuntimeError(f"Release tab mismatch before harvest: expected {key}, got {active_key}")

    records = visible_record_release_tags(page)
    if require_rows and not records:
        raise RuntimeError(f"release scope check found no rendered rows for {cfg.release}")

    tagged = 0
    mismatched = []

    for rec in records:
        tags = set(rec.get("tags") or [])
        tags.update(link.get("dataRelease") for link in rec.get("links") or [] if link.get("dataRelease"))
        tags = {str(tag).strip().lower() for tag in tags if str(tag).strip()}

        if not tags:
            continue

        tagged += 1
        bad = sorted(tag for tag in tags if tag not in {key, str(int(key))})
        if bad:
            mismatched.append({"text": rec.get("text", ""), "tags": bad})

    if mismatched:
        examples = "; ".join(
            f"{item['tags']} on {item['text'][:80]}" for item in mismatched[:5]
        )
        raise RuntimeError(f"release scope check found visible record tags outside {key}: {examples}")

    print(
        f"[WarRip] Release scope check: active={active_key} "
        f"visible_rows={len(records)} tagged_rows={tagged}"
    )
    return {"active": active, "records": records, "tagged_rows": tagged}


def goto_release_page(page, cfg, *, wait_ms=4000, require_rows=False):
    print("[WarRip] Opening base UFO page...")
    page.goto(BASE_UFO_URL, wait_until="domcontentloaded", timeout=90000)
    page.wait_for_timeout(max(500, int(wait_ms / 2)))

    print(f"[WarRip] Opening release URL: {cfg.start_url}")
    page.goto(cfg.start_url, wait_until="domcontentloaded", timeout=90000)
    page.wait_for_timeout(wait_ms)
    print(f"[WarRip] URL loaded: {page.url}")

    select_release_tab(page, cfg)
    validate_release_scope(page, cfg, require_rows=require_rows)
