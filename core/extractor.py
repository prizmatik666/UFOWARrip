# UFOWARrip
# Created by Prizmatik
# https://github.com/prizmatik666/UFOWARrip

import re


def safe_asset_name(text: str) -> str | None:
    text = (text or "").strip()
    if not text:
        return None

    bad = {"FILES", "AGENCY", "RELEASE DATE", "INCIDENT DATE", "INCIDENT LOCATION"}
    if text.upper() in bad:
        return None

    if len(text) < 4:
        return None

    if not re.search(r"[A-Za-z0-9]", text):
        return None

    return re.sub(r"\s+", "_", text.strip())


def build_pdf_url(cfg, asset_name: str) -> str:
    clean = asset_name.strip()
    clean = re.sub(r"\.pdf$", "", clean, flags=re.I)
    return f"https://www.war.gov/medialink/ufo/{cfg.release}/{clean.lower()}.pdf"


def extract_visible_records(page, cfg, page_num: int):
    rows = page.evaluate(
        """
        () => {
          const visibleEnough = el => {
            const r = el.getBoundingClientRect();
            const s = window.getComputedStyle(el);
            return r.width > 20 &&
                   r.height > 5 &&
                   s.display !== 'none' &&
                   s.visibility !== 'hidden' &&
                   s.opacity !== '0';
          };

          const out = [];

          const tableRows = [...document.querySelectorAll('tr')]
            .filter(visibleEnough)
            .map(tr => [...tr.querySelectorAll('td, th')].map(td => (td.innerText || '').trim()))
            .filter(cells => cells.length >= 1);

          for (const cells of tableRows) {
            out.push({kind: 'tr', cells});
          }

          const buttonRows = [...document.querySelectorAll('button')]
            .filter(visibleEnough)
            .map(b => (b.innerText || '').trim())
            .filter(t => t.length > 0)
            .map(t => t.split('\\n').map(x => x.trim()).filter(Boolean))
            .filter(cells => cells.length >= 1);

          for (const cells of buttonRows) {
            out.push({kind: 'button', cells});
          }

          return out;
        }
        """
    )

    records = []
    seen = set()

    for row in rows:
        cells = row.get("cells") or []
        if not cells:
            continue

        asset = safe_asset_name(cells[0])
        if not asset:
            continue

        # Skip pagination/nav junk
        if asset.upper() in {"PREV", "NEXT", "DOWNLOAD", "CLOSE"}:
            continue

        # Require filename-ish rows: underscores/digits/hyphens or known doc-ish naming
        if "_" not in asset and "-" not in asset and not re.search(r"\d", asset):
            continue

        if asset in seen:
            continue
        seen.add(asset)

        agency = cells[1].strip("[]") if len(cells) > 1 else ""
        release_date = cells[2].strip("[]") if len(cells) > 2 else ""
        incident_date = cells[3].strip("[]") if len(cells) > 3 else ""
        incident_location = cells[4].strip("[]") if len(cells) > 4 else ""
        document_type = cells[5].strip("[]") if len(cells) > 5 else ".PDF"

        records.append({
            "asset_name": asset,
            "agency": agency,
            "release_date": release_date,
            "incident_date": incident_date,
            "incident_location": incident_location,
            "document_type": document_type or ".PDF",
            "release": cfg.release,
            "url": build_pdf_url(cfg, asset),
            "url_source": "generated_from_asset_name",
            "confidence": "medium",
            "seen_on_pages": [page_num],
            "raw_cells": cells,
        })

    return records


def active_page_number(page):
    try:
        txt = page.evaluate(
            """
            () => {
              const active = document.querySelector('.pagination-button.is-active');
              return active ? active.innerText.trim() : '';
            }
            """
        )
        return int(txt) if txt.isdigit() else None
    except Exception:
        return None
