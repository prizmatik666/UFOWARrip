# UFOWARrip

Current version: WarRip v3.2

UFOWARrip is a browser-observed download pipeline for the public `war.gov/UFO/` release page.

Created by Prizmatik  
https://github.com/prizmatik666/UFOWARrip

## What It Does

The war.gov UFO/UAP release page is dynamic and browser-dependent. Direct URL guessing and direct HTTP requests can fail or produce bad files. UFOWARrip works around that by using Playwright/Chromium to observe the real site behavior:

- builds an index from the visible release records
- harvests real PDF URLs from row modal download buttons
- harvests image URLs from `.IMG` records
- harvests video URLs from `.VID` records by capturing direct CloudFront MP4 requests
- harvests audio-labeled `.AUD` records while preserving their source label, even when the payload is an `.mp4`
- downloads harvested media only after validating file magic bytes and minimum size
- stores PDFs, images, videos, and audio-labeled media in separate folders

## Included Seed Indexes

This repository includes clean per-release indexes under:

```text
war_ufo_data/data/index_release_1.json
war_ufo_data/data/index_release_2.json
war_ufo_data/data/aaro_index.json
```

That means new users can download harvested media right away without running the site observation or URL harvesting steps first.

The included War Department indexes cover Release 1 and Release 2. The included AARO index covers the AARO official UAP imagery/incidents dataset handled by the companion AARO script.

The included indexes contain observed record metadata and harvested URLs, but they have fresh download state. Local paths, hashes, failed attempts, and machine-specific download records were reset before publishing.

At startup, UFOWARrip asks which release number to work on. The release number controls both the browser URL and the local index file. For example:

```text
1 -> https://www.war.gov/UFO/?releaseDate=Release+01#records
2 -> https://www.war.gov/UFO/?releaseDate=Release+02#records
```

Single-digit release numbers are zero-padded in the site URL.

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

The program first asks for a release number, such as `1` or `2`. Press Enter to keep the configured default.

If you are on SSH/headless and cannot spawn a browser directly, use Xvfb:

```bash
python3 -m py_compile warrip.py core/*.py && xvfb-run -a python3 warrip.py
```

The compile step is optional, but useful before long browser runs because it catches syntax errors first.

## Recommended Workflow

Because fresh Release 1, Release 2, and AARO indexes are included, most users can skip observe/build-index and URL harvesting. For War Department releases, choose the release number at startup, then go straight to:

```text
[6] Download harvested media
```

Then choose:

```text
[1] PDFs
[2] Images
[3] Videos
[4] Audio
[5] All
```

If you want to refresh or rebuild data from the live site:

```text
[1] Observe site / build index
[2] Harvest PDF download URLs
[3] Harvest image download URLs
[4] Harvest video download URLs
[5] Harvest audio download URLs
[6] Download harvested media
```

Mode `[1]` is not required every run. Use it when the selected release index is missing, stale, damaged, or the release page has changed.

## Menu Options

```text
[1] Observe site / build index
```

Opens the release page and records visible page/card metadata into the index.

The URL is derived from the selected release number. For release `2`, mode `[1]` opens:

```text
https://www.war.gov/UFO/?releaseDate=Release+02#records
```

Observed records are saved to the matching per-release index, such as:

```text
war_ufo_data/data/index_release_2.json
```

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
[5] Harvest audio download URLs
```

Processes records visibly marked `[.AUD]`. The site labels these as audio records, but the final media endpoint may still be an `.mp4` file. UFOWARrip preserves the source `.AUD` label in the index and stores accepted downloads under the audio folder.

```text
[6] Download harvested media
```

Downloads selected media types from harvested URLs only. It does not use guessed/generated candidate URLs by default.

Downloads go to:

```text
war_ufo_data/downloads/release_1/pdf/
war_ufo_data/downloads/release_1/img/
war_ufo_data/downloads/release_1/vid/
war_ufo_data/downloads/release_1/aud/
```

The downloader validates files before accepting them:

- PDFs must start with `%PDF` and be at least 8 KB
- images must match PNG/JPEG/GIF/WEBP magic bytes and be at least 1 KB
- videos and audio-labeled `.AUD` payloads must look like MP4 files and be at least 100 KB

Existing valid files are not overwritten.

```text
[7] Observe + PDF harvest + download PDFs
```

Runs a combined PDF-focused workflow.

```text
[8] Verify downloads
```

Checks downloaded files for all media types and updates download metadata. If files are missing or invalid, the verifier prints practical next steps for rerunning the download pass.

```text
[9] Export URL list
```

Exports final harvested endpoint URLs. These are not observe-time guesses. You can choose:

- PDFs
- Images
- Videos
- Audio
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

Candidate URLs from observe/build-index are written separately as:

```text
candidate_urls_release_N.txt
```

Final harvested endpoint exports use names such as:

```text
harvested_pdf_urls_release_N.txt
harvested_image_urls_release_N.txt
harvested_video_urls_release_N.txt
harvested_audio_urls_release_N.txt
harvested_all_urls_release_N.txt
```

```text
[10] Show summary
```

Prints a quick index/download summary.

```text
[11] Settings
```

Opens the settings submenu.

```text
[12] Change release
```

Switches the active release number, browser URL, index file, exports, and download folder.

## Settings

```text
Release number
```

The release number to work on. Default:

```text
1
```

This controls the site URL. For example, release `1` maps to `Release+01`, and release `2` maps to `Release+02`.

```text
Release/subfolder
```

The local release label is derived from the release number. Default:

```text
release_1
```

This is mainly used for download folders:

```text
war_ufo_data/downloads/release_1/
```

It also controls the active index and URL export filenames.

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

If UFOWARrip reaches this limit and detects that more page numbers are available, it prompts:

```text
Continue scanning? [Y/n]
```

Continuing extends only the current run's temporary scan limit. It does not change the saved setting.

## Important Notes

- The harvesters are intentionally separate for PDFs, images, videos, and audio-labeled records because each media type behaves differently on the site.
- Direct Python requests to war.gov can return `403`; browser context matters.
- The downloader rejects tiny or fake files. This prevents saving old 536-byte error bodies as successful PDFs.
- Video player `blob:` URLs are not real downloadable source URLs. UFOWARrip captures direct `.mp4` network URLs instead.
- `.AUD` records may also resolve to `.mp4` endpoints. They remain classified as audio in the index for fidelity to the source site label.
- Observe/build-index candidate URL exports are not final truth. Use `harvested_*_urls_release_N.txt` files for confirmed endpoint lists.
- Re-running a harvester or downloader is safe. Existing good URLs/files are skipped or verified rather than overwritten.

## Main Files

```text
aaro_rip.py               aaro video harvester tool
warrip.py                 menu launcher
core/browser_session.py   persistent Chromium session
core/observer.py          site/page observer
core/harvester.py         PDF URL harvester
core/image_harvester.py   image URL harvester
core/video_harvester.py   video URL harvester
core/audio_harvester.py   audio-labeled URL harvester
core/downloader.py        validated media downloader
core/index_store.py       index load/save/export helpers
core/pagination.py        shared pagination continuation prompts
```
## Reconciliation / Audit Tool

UFOWARrip includes a standalone reconciliation tool:

```bash
python3 reconcile_index.py
```

The tool detects available `index_release_N.json` files and `aaro_index.json`, then asks which index to reconcile. For WAR releases, it uses the release number to form the matching live site URL, crawls the rendered records, and compares the site rows against the selected local index. For AARO, it parses the official AARO imagery page and compares those entries against `aaro_index.json`.

You can also run it directly for a release:

```bash
python3 reconcile_index.py --release 2
```

Or reconcile AARO directly:

```bash
python3 reconcile_index.py --aaro
```

If AARO blocks live requests or you want a reproducible offline audit, use a saved page source:

```bash
python3 reconcile_index.py --aaro --aaro-html saved_aaro_page.html
```

WAR release reconciliation writes per-release outputs:

```text
war_ufo_data/data/reconciliation_report_release_N.json
war_ufo_data/data/missing_records_release_N.txt
```

AARO reconciliation writes:

```text
war_ufo_data/data/reconciliation_report_aaro.json
war_ufo_data/data/missing_records_aaro.txt
```

The report includes observed site count, local index count, PDF/image/video/audio counts, records present on the site but absent from the index, records in the index but not found on the site, and duplicate normalized records.

## AARO Official UAP Imagery Harvester (`aaro_rip.py`)

UFOWARrip includes a dedicated AARO (All-domain Anomaly Resolution Office) harvesting utility for collecting officially released UAP/UFO imagery and videos directly from:

https://www.aaro.mil/UAP-Cases/Official-UAP-Imagery/

Unlike the main WAR pipeline, the AARO utility works by parsing the public AARO page itself and extracting embedded DVIDS/CloudFront MP4 sources and metadata.

### AARO Output Structure

```text
war_ufo_data/
  data/
    aaro_index.json
  downloads/
    aaro/
      PR-018_*.mp4
      PR-018_*.txt
      PR-017_*.mp4
      ...
```

Each downloaded MP4 receives a matching `.txt` metadata sidecar with title, incident ID, description, DVIDS source URL, original MP4 URL, local filename correlation, and source attribution.

Launch the interactive AARO UI with:

```bash
python3 aaro_rip.py
```

Menu options:

```text
1) Scan AARO page / update index only
2) Download missing AARO videos
3) Force re-download all AARO videos
4) Show local AARO status
5) Verify downloaded MP4 files
6) Use local saved HTML source
0) Exit
```

## Output Layout

```text
war_ufo_data/
  data/
    aaro_index.json
    index_release_1.json
    index_release_2.json
    candidate_urls_release_1.txt
    harvested_pdf_urls_release_1.txt
    harvested_image_urls_release_1.txt
    harvested_video_urls_release_1.txt
    harvested_audio_urls_release_1.txt
  downloads/
    aaro/
    release_1/
      pdf/
      img/
      vid/
      aud/
    release_2/
      pdf/
      img/
      vid/
      aud/
  debug/
  logs/
```
