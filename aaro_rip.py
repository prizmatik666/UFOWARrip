#!/usr/bin/env python3
"""
UFOWARrip AARO UI utility

Downloads embedded AARO/DVIDS MP4s from:
https://www.aaro.mil/UAP-Cases/Official-UAP-Imagery/

Saves:
  war_ufo_data/data/downloads/aaro/*.mp4
  war_ufo_data/data/downloads/aaro/*.txt
  war_ufo_data/data/aaro_index.json
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


AARO_URL = "https://www.aaro.mil/UAP-Cases/Official-UAP-Imagery/"

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_DATA_DIR = SCRIPT_DIR / "war_ufo_data" / "data"
DEFAULT_OUT_DIR = DEFAULT_DATA_DIR / "downloads" / "aaro"
DEFAULT_INDEX = DEFAULT_DATA_DIR / "aaro_index.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:139.0) "
        "Gecko/20100101 Firefox/139.0"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Priority": "u=0, i",
}

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def pause() -> None:
    input("\nPress Enter to continue...")


def hr() -> None:
    print("=" * 72)


def title_screen() -> None:
    print("\n")
    hr()
    print(" UFOWARrip :: AARO Official UAP Imagery Harvester")
    hr()
    print(f" Source : {AARO_URL}")
    print(f" Index  : {DEFAULT_INDEX}")
    print(f" Output : {DEFAULT_OUT_DIR}")
    hr()


def ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    val = input(f"{prompt}{suffix}: ").strip()
    return val or default


def confirm(prompt: str, default: bool = False) -> bool:
    d = "y" if default else "n"
    val = ask(f"{prompt} (y/n)", d).lower()
    return val in {"y", "yes"}


def slugify(text: str, max_len: int = 120) -> str:
    text = text.strip()
    text = re.sub(r"[^\w\s.-]+", "", text, flags=re.UNICODE)
    text = re.sub(r"\s+", "_", text)
    text = text.strip("._-")
    return text[:max_len] or "aaro_video"


def clean_text(node) -> str:
    if not node:
        return ""
    return " ".join(node.get_text(" ", strip=True).split())


def load_index(path: Path = DEFAULT_INDEX) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {
        "source": "aaro",
        "source_url": AARO_URL,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "items": {},
    }


def save_index(index: dict, path: Path = DEFAULT_INDEX) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    index["updated_at"] = now_iso()
    path.write_text(json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8")


def fetch_html(source: str | None = None) -> str:
    if source:
        p = Path(source).expanduser()
        if p.exists():
            return p.read_text(encoding="utf-8", errors="replace")
        print(f"[!] Source HTML not found: {p}")
        return ""

    session = requests.Session()
    session.headers.update(HEADERS)

    r = session.get(AARO_URL, timeout=30)
    if r.status_code == 403:
        raise RuntimeError(
            "AARO returned 403. Try option 6 with saved HTML source, "
            "or install curl_cffi fallback later."
        )

    r.raise_for_status()
    return r.text

def extract_items(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    items = {}

    for row in soup.select("tr[data-id]"):
        pr_id = row.get("data-id", "").strip()
        cells = row.find_all("td")
        if len(cells) < 4:
            continue

        title = clean_text(cells[1])
        link = cells[2].find("a", href=True)
        dvids_url = urljoin(AARO_URL, link["href"]) if link else ""
        description = clean_text(cells[3])

        extra = soup.select_one(f"#extra-{pr_id}")
        video = extra.find("video") if extra else None

        mp4_url = video.get("src", "").strip() if video else ""
        poster_url = video.get("poster", "").strip() if video else ""
        video_label = video.get("aria-label", "").strip() if video else ""

        if not title:
            continue

        key = pr_id or slugify(title)
        items[key] = {
            "id": pr_id,
            "title": title,
            "description": description,
            "dvids_url": dvids_url,
            "mp4_url": mp4_url,
            "poster_url": poster_url,
            "video_label": video_label,
            "source_url": AARO_URL,
        }

    for row in soup.select("tr"):
        video = row.find("video")
        if not video or not video.get("src"):
            continue

        cells = row.find_all("td")
        if len(cells) < 4:
            continue

        title = clean_text(cells[0])
        link = cells[1].find("a", href=True)
        dvids_url = urljoin(AARO_URL, link["href"]) if link else ""
        description = clean_text(cells[2])
        mp4_url = video.get("src", "").strip()

        pr_match = re.search(r"\bPR-\d{3}\b", title)
        pr_id = pr_match.group(0) if pr_match else ""
        key = pr_id or slugify(title)

        items.setdefault(key, {
            "id": pr_id,
            "title": title,
            "description": description,
            "dvids_url": dvids_url,
            "mp4_url": mp4_url,
            "poster_url": video.get("poster", "").strip(),
            "video_label": video.get("aria-label", "").strip(),
            "source_url": AARO_URL,
        })

    deduped = {}
    seen_mp4 = set()

    for item in items.values():
        mp4 = item.get("mp4_url", "").strip()
        if mp4 and mp4 in seen_mp4:
            continue
        if mp4:
            seen_mp4.add(mp4)
        deduped[item["id"] or item["title"]] = item

    return list(deduped.values())


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def download_file(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")

    with requests.get(url, headers=HEADERS, stream=True, timeout=(10, 60)) as r:
        r.raise_for_status()
        ctype = r.headers.get("content-type", "")
        clen = r.headers.get("content-length", "?")
        print(f"    status={r.status_code} type={ctype or '?'} size={clen}")

        with tmp.open("wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)

    tmp.replace(dest)


def write_sidecar(item: dict, mp4_path: Path, txt_path: Path) -> None:
    txt = f"""Title:
{item.get("title", "")}

ID:
{item.get("id", "")}

Description:
{item.get("description", "")}

Video label:
{item.get("video_label", "")}

DVIDS URL:
{item.get("dvids_url", "")}

MP4 URL:
{item.get("mp4_url", "")}

Local MP4:
{mp4_path.name}

Source:
{item.get("source_url", AARO_URL)}
"""
    txt_path.write_text(txt, encoding="utf-8")


def build_index_only(source_html: str | None = None, dry_label: bool = True) -> list[dict]:
    html = fetch_html(source_html)
    if not html:
        return []

    found = extract_items(html)
    index = load_index()
    index.setdefault("items", {})

    print(f"[+] Found {len(found)} AARO video entries")

    for item in found:
        key = item["id"] or slugify(item["title"])
        safe_name = slugify(f"{key}_{item['title']}")
        mp4_path = DEFAULT_OUT_DIR / f"{safe_name}.mp4"
        txt_path = DEFAULT_OUT_DIR / f"{safe_name}.txt"

        existing = index["items"].get(key, {})
        merged = {
            **existing,
            **item,
            "first_seen": existing.get("first_seen", now_iso()),
            "last_seen": now_iso(),
            "local_mp4": str(mp4_path),
            "local_txt": str(txt_path),
            "downloaded": existing.get("downloaded", False),
            "sha256": existing.get("sha256"),
            "size_bytes": existing.get("size_bytes"),
        }

        if dry_label:
            print(f"[DRY] {key} -> {item.get('mp4_url', 'NO MP4')}")

        index["items"][key] = merged

    save_index(index)
    print(f"[+] Index saved: {DEFAULT_INDEX}")
    return found


def download_missing(force: bool = False, source_html: str | None = None) -> None:
    html = fetch_html(source_html)
    if not html:
        return

    found = extract_items(html)
    index = load_index()
    index.setdefault("items", {})

    print(f"[+] Found {len(found)} AARO video entries")

    for item in found:
        key = item["id"] or slugify(item["title"])
        safe_name = slugify(f"{key}_{item['title']}")
        mp4_path = DEFAULT_OUT_DIR / f"{safe_name}.mp4"
        txt_path = DEFAULT_OUT_DIR / f"{safe_name}.txt"

        existing = index["items"].get(key, {})
        merged = {
            **existing,
            **item,
            "first_seen": existing.get("first_seen", now_iso()),
            "last_seen": now_iso(),
            "local_mp4": str(mp4_path),
            "local_txt": str(txt_path),
            "downloaded": existing.get("downloaded", False),
            "sha256": existing.get("sha256"),
        }

        if not item.get("mp4_url"):
            print(f"[!] No MP4 URL for {key}: {item['title']}")
            index["items"][key] = merged
            continue

        if mp4_path.exists() and not force:
            print(f"[=] Exists: {mp4_path.name}")
        else:
            print(f"[↓] Downloading: {mp4_path.name}")
            try:
                download_file(item["mp4_url"], mp4_path)
            except Exception as e:
                print(f"[!] Download failed for {key}: {e}")
                index["items"][key] = merged
                save_index(index)
                continue

        write_sidecar(item, mp4_path, txt_path)

        merged["downloaded"] = mp4_path.exists()
        merged["sha256"] = sha256_file(mp4_path) if mp4_path.exists() else None
        merged["size_bytes"] = mp4_path.stat().st_size if mp4_path.exists() else None
        index["items"][key] = merged
        save_index(index)

    print(f"[+] Index saved: {DEFAULT_INDEX}")
    print(f"[+] Downloads:   {DEFAULT_OUT_DIR}")


def show_status() -> None:
    index = load_index()
    items = index.get("items", {})

    total = len(items)
    downloaded = sum(1 for x in items.values() if x.get("downloaded"))
    missing = total - downloaded

    print()
    hr()
    print(" AARO Status")
    hr()
    print(f"Indexed entries : {total}")
    print(f"Downloaded      : {downloaded}")
    print(f"Missing         : {missing}")
    print(f"Index path      : {DEFAULT_INDEX}")
    print(f"Download path   : {DEFAULT_OUT_DIR}")
    hr()


def verify_downloads() -> None:
    index = load_index()
    items = index.get("items", {})

    if not items:
        print("[!] No index entries found.")
        return

    print("[+] Verifying indexed MP4 files...")
    bad = 0
    ok = 0

    for key, item in items.items():
        mp4_path = Path(item.get("local_mp4", ""))
        if not mp4_path.exists():
            print(f"[MISSING] {key} -> {mp4_path}")
            bad += 1
            continue

        with mp4_path.open("rb") as f:
            head = f.read(32)

        if b"ftyp" not in head:
            print(f"[BAD?] {key} -> no ftyp atom near file start: {mp4_path.name}")
            bad += 1
        else:
            ok += 1

    print(f"[+] OK: {ok}")
    print(f"[+] Problems: {bad}")

    if shutil.which("ffprobe"):
        if confirm("Run ffprobe verification too?", False):
            for key, item in items.items():
                mp4_path = Path(item.get("local_mp4", ""))
                if mp4_path.exists():
                    print(f"\n== {mp4_path.name} ==")
                    import subprocess
                    subprocess.run([
                        "ffprobe",
                        "-v", "error",
                        "-show_entries", "format=duration,size",
                        "-of", "default=nw=1",
                        str(mp4_path),
                    ])


def menu() -> None:
    while True:
        title_screen()
        print("1) Scan AARO page / update index only")
        print("2) Download missing AARO videos")
        print("3) Force re-download all AARO videos")
        print("4) Show local AARO status")
        print("5) Verify downloaded MP4 files")
        print("6) Use local saved HTML source")
        print("0) Exit")
        print()

        choice = ask("Select option")

        try:
            if choice == "1":
                build_index_only()
                pause()
            elif choice == "2":
                download_missing(force=False)
                pause()
            elif choice == "3":
                if confirm("Force re-download every indexed AARO MP4?", False):
                    download_missing(force=True)
                pause()
            elif choice == "4":
                show_status()
                pause()
            elif choice == "5":
                verify_downloads()
                pause()
            elif choice == "6":
                src = ask("Path to saved AARO HTML/source file")
                if not src:
                    print("[!] No source path entered.")
                else:
                    print("1) Index only from local source")
                    print("2) Download from local source")
                    sub = ask("Select option")
                    if sub == "1":
                        build_index_only(source_html=src)
                    elif sub == "2":
                        download_missing(force=False, source_html=src)
                    else:
                        print("[!] Invalid option.")
                pause()
            elif choice == "0":
                print("Exiting AARO harvester.")
                return
            else:
                print("[!] Invalid option.")
                pause()
        except KeyboardInterrupt:
            print("\n[!] Interrupted.")
            pause()
        except Exception as e:
            print(f"\n[!] Error: {e}")
            pause()


if __name__ == "__main__":
    menu()
