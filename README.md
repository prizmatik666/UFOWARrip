# UFOWARrip

* I will be waiting till they release a new chunk of files before choosing how to proceed with further updates*
* depending on what they do, may implement ability to scan a range of pages, or start at a certain page, like epstein-ripper has*
  
UFOWARrip is a browser-observed download pipeline for the public `war.gov/UFO/` release page.

Created by Prizmatik  
https://github.com/prizmatik666/UFOWARrip

## What It Does

The war.gov UFO/UAP release page is dynamic and browser-dependent. Direct URL guessing and direct HTTP requests can fail or produce bad files. UFOWARrip works around that by using Playwright/Chromium to observe the real site behavior:

- builds an index from the visible release records
- harvests real PDF URLs from row modal download buttons
- harvests image URLs from `.IMG` records
- harvests video URLs from `.VID` records by capturing direct CloudFront MP4 requests
- downloads harvested media only after validating file magic bytes and minimum size
- stores PDFs, images, and videos in separate folders

## Included Seed Index

This repository includes a clean first-release index at:

```text
war_ufo_data/data/index.json
```

That means new users can download harvested media right away without running the site observation step first.

The included index contains observed record metadata and harvested URLs, but it has fresh download state. Local paths, hashes, failed attempts, and machine-specific download records were reset before publishing.

## Requirements

- Python 3
- Playwright
- requests
- Chromium dependencies needed by Playwright
- `xvfb-run` if running over SSH/headless while using browser automation

Install Python dependencies:

```bash
pip install -r requirements.txt
python3 -m playwright install chromium
```

On some Linux systems, Playwright may also need system packages:

```bash
python3 -m playwright install-deps chromium
```

## Running

On a normal desktop machine that can open a browser:

```bash
python3 warrip.py
```

If you are on SSH/headless and cannot spawn a browser directly, use Xvfb:

```bash
python3 -m py_compile warrip.py core/*.py && xvfb-run -a python3 warrip.py
```

The compile step is optional, but useful before long browser runs because it catches syntax errors first.

## Recommended Workflow

Because the first release index is included, the fastest path is:

```text
[5] Download harvested media
```

Then choose:

```text
[1] PDFs
[2] Images
[3] Videos
[4] All
```

If you want to refresh or rebuild data from the live site:

```text
[1] Observe site / build index
[2] Harvest PDF download URLs
[3] Harvest image download URLs
[4] Harvest video download URLs
[5] Download harvested media
```

Mode `[1]` is not required every run. Use it when the index is missing, stale, damaged, or the release page has changed.

## Menu Options

```text
[1] Observe site / build index
```

Opens the release page and records visible page/card metadata into the index.

```text
[2] Harvest PDF download URLs
```

Processes only records visibly marked `[.PDF]`. It opens each PDF modal, clicks Download, captures the real `/medialink/ufo/...pdf` URL, and stores it as a high-confidence URL.

```text
[3] Harvest image download URLs
```

Processes only records visibly marked `[.IMG]`. It captures image URLs such as `.png`, `.jpg`, `.jpeg`, `.gif`, and `.webp`.

```text
[4] Harvest video download URLs
```

Processes only records visibly marked `[.VID]`. It clicks Download Video and captures direct `.mp4` network URLs, usually from CloudFront. It does not store browser-local `blob:` URLs as final video URLs.

```text
[5] Download harvested media
```

Downloads selected media types from harvested URLs only. It does not use guessed/generated candidate URLs by default.

Downloads go to:

```text
war_ufo_data/downloads/release_1/pdf/
war_ufo_data/downloads/release_1/img/
war_ufo_data/downloads/release_1/vid/
```

The downloader validates files before accepting them:

- PDFs must start with `%PDF` and be at least 8 KB
- images must match PNG/JPEG/GIF/WEBP magic bytes and be at least 1 KB
- videos must look like MP4 files and be at least 100 KB

Existing valid files are not overwritten.

```text
[6] Observe + PDF harvest + download PDFs
```

Runs a combined PDF-focused workflow.

```text
[7] Verify downloads
```

Checks downloaded files and updates download metadata.

```text
[8] Export URL list
```

Exports harvested URLs. You can choose:

- PDFs
- Images
- Videos
- All

You can also choose plain format or numbered format for posting:

```text
1) https://example/url
2) https://example/url
```

Exports are written under:

```text
war_ufo_data/data/
```

```text
[9] Show summary
```

Prints a quick index/download summary.

```text
[10] Settings
```

Opens the settings submenu.

## Settings

```text
Start URL
```

The release page to observe. Default:

```text
https://www.war.gov/UFO/
```

```text
Release/subfolder
```

The local release label. Default:

```text
release_1
```

This is mainly used for download folders:

```text
war_ufo_data/downloads/release_1/
```

It also still matters for older generated URL metadata, so keep it aligned with the release tranche.

```text
Output dir
```

Root output folder. Default:

```text
war_ufo_data
```

```text
Browser headed
```

Whether Chromium should open visibly. Default is `True`.

Use `True` on a desktop with a display. Use `False`, or run through `xvfb-run`, on SSH/headless systems.

```text
Stable wait ms
```

Wait time used between dynamic page actions. Increase this if the site is slow or modals/pagination are not settling.

```text
Max pages
```

Maximum number of release pages to scan/harvest. Default is `30`.

## Important Notes

- The harvesters are intentionally separate for PDFs, images, and videos because each media type behaves differently on the site.
- Direct Python requests to war.gov can return `403`; browser context matters.
- The downloader rejects tiny or fake files. This prevents saving old 536-byte error bodies as successful PDFs.
- Video player `blob:` URLs are not real downloadable source URLs. UFOWARrip captures direct `.mp4` network URLs instead.
- Re-running a harvester or downloader is safe. Existing good URLs/files are skipped or verified rather than overwritten.

## Main Files

```text
warrip.py                 menu launcher
core/browser_session.py   persistent Chromium session
core/observer.py          site/page observer
core/harvester.py         PDF URL harvester
core/image_harvester.py   image URL harvester
core/video_harvester.py   video URL harvester
core/downloader.py        validated media downloader
core/index_store.py       index load/save/export helpers
```
## Side Tool
  Some public posts rounded or reported the release as roughly 162 files, while
  the live release page observed by UFOWARrip showed 161 rendered rows. The local
  seed index contains 158 unique assets because the site includes duplicate
  rendered rows for the same normalized asset/title/type entries: one duplicate
  instance of DOW-UAP-D23 and two duplicate instances of DOW-UAP-D32. In other
  words, UFOWARrip preserves the 158 unique downloadable assets rather than
  counting duplicate rows as separate files.

  ## Reconciliation / Audit Tool

  UFOWARrip includes a standalone reconciliation tool:

  ```bash
  python3 reconcile_index.py

  The tool audits the public release page against the local war_ufo_data/data/
  index.json without modifying the main application workflow. It crawls the
  rendered records, counts visible rows/cards, extracts each record title, media
  type, and page number, then compares those rendered records against the local
  index.

  It writes:

  war_ufo_data/data/reconciliation_report.json
  war_ufo_data/data/missing_records.txt

  The report includes:

  - observed site count
  - local index count
  - PDF/image/video counts
  - records present on the site but absent from the index
  - records in the index but not found on the site
  - duplicate normalized records

  If live browser/network rendering is unavailable, but debug page snapshots exist
  from a prior observation run, the audit can be run against those saved rendered
  pages:

  python3 reconcile_index.py --from-debug-html

  That mode reads:

  war_ufo_data/debug/html/page_*.html

  This is useful for investigating count discrepancies without rebuilding the
  index. For example, the release page may display duplicate visible rows that
  normalize to the same asset title/type key, causing the rendered site count to
  be higher than the unique local index count.

## Output Layout

```text
war_ufo_data/
  data/
    index.json
    urls.txt
    image_urls.txt
    video_urls.txt
  downloads/
    release_1/
      pdf/
      img/
      vid/
  debug/
  logs/
```

