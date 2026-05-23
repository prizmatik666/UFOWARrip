#!/usr/bin/env python3
#
# UFOWARrip
# Created by Prizmatik
# https://github.com/prizmatik666/UFOWARrip

from core.config import Config
from core.logger import log
from core.observer import observe_site
from core.harvester import harvest_pdf_urls
from core.image_harvester import harvest_image_urls
from core.video_harvester import harvest_video_urls
from core.audio_harvester import harvest_audio_urls
from core.downloader import download_media_types, download_missing
from core.verifier import verify_downloads
from core.index_store import export_harvested_urls, index_path, load_index, summarize_index


APP_NAME = "WarRip v3.2"


def menu():
    cfg = Config.load()
    select_release(cfg)

    while True:
        print(f"\n=== {APP_NAME} | {cfg.release} ===")
        print(f"URL: {cfg.start_url}")
        print(f"Index: {index_path(cfg)}")
        print("[1] Observe site / build index")
        print("[2] Harvest PDF download URLs")
        print("[3] Harvest image download URLs")
        print("[4] Harvest video download URLs")
        print("[5] Harvest audio download URLs")
        print("[6] Download harvested media")
        print("[7] Observe + PDF harvest + download PDFs")
        print("[8] Verify downloads")
        print("[9] Export URL list")
        print("[10] Show summary")
        print("[11] Settings")
        print("[12] Change release")
        print("[0] Exit")

        choice = input("\nChoose: ").strip()

        try:
            if choice == "1":
                observe_site(cfg)
            elif choice == "2":
                harvest_pdf_urls(cfg)
            elif choice == "3":
                harvest_image_urls(cfg)
            elif choice == "4":
                harvest_video_urls(cfg)
            elif choice == "5":
                harvest_audio_urls(cfg)
            elif choice == "6":
                download_missing(cfg)
            elif choice == "7":
                observe_site(cfg)
                harvest_pdf_urls(cfg)
                download_media_types(cfg, ["pdf"])
            elif choice == "8":
                verify_downloads(cfg)
            elif choice == "9":
                export_url_menu(cfg)
            elif choice == "10":
                summarize_index(cfg)
            elif choice == "11":
                settings(cfg)
            elif choice == "12":
                select_release(cfg)
            elif choice == "0":
                print("Later, space cowboy.")
                return
            else:
                print("[!] Invalid choice.")
        except KeyboardInterrupt:
            print("\n[!] Interrupted. Back to menu.")
        except Exception as e:
            print(f"[!] Error: {e}")
            log(cfg, f"Unhandled error: {e}")


def select_release(cfg):
    while True:
        current = getattr(cfg, "release_number", 1)
        print("\n=== Select Release ===")
        print(f"Current: {cfg.release} | {cfg.start_url}")
        val = input("Release number, example 1 or 2: ").strip()

        if not val:
            return

        if not val.isdigit() or int(val) < 1:
            print("[!] Enter a release number 1 or greater.")
            continue

        cfg.set_release(int(val))
        if int(val) == current:
            print(f"[✓] Using {cfg.release}.")
        else:
            print(f"[✓] Switched to {cfg.release}.")
        print(f"    URL: {cfg.start_url}")
        return


def settings(cfg):
    while True:
        print("\n=== Settings ===")
        print(f"[1] Release number:   {cfg.release_number}")
        print(f"[2] Release/subfolder:{cfg.release}")
        print(f"    Start URL:        {cfg.start_url}")
        print(f"[3] Output dir:       {cfg.output_dir}")
        print(f"[4] Browser headed:   {cfg.headed}")
        print(f"[5] Stable wait ms:   {cfg.stable_wait_ms}")
        print(f"[6] Max pages:        {cfg.max_pages}")
        print("[0] Back")

        choice = input("\nChoose: ").strip()

        if choice == "1":
            val = input("Release number, example 1 or 2: ").strip()
            if val.isdigit() and int(val) >= 1:
                cfg.set_release(int(val))
                print(f"[✓] Release: {cfg.release}")
                print(f"    URL: {cfg.start_url}")

        elif choice == "2":
            print("[WarRip] Release/subfolder is derived from the release number.")
            print(f"         Current: {cfg.release}")

        elif choice == "3":
            val = input("Output dir: ").strip()
            if val:
                cfg.output_dir = val
                cfg.save()

        elif choice == "4":
            cfg.headed = not cfg.headed
            cfg.save()
            print(f"[✓] Browser headed: {cfg.headed}")

        elif choice == "5":
            val = input("Stable wait ms: ").strip()
            if val.isdigit():
                cfg.stable_wait_ms = int(val)
                cfg.save()

        elif choice == "6":
            val = input("Max pages: ").strip()
            if val.isdigit():
                cfg.max_pages = int(val)
                cfg.save()

        elif choice == "0":
            return

        else:
            print("[!] Invalid choice.")


def export_url_menu(cfg):
    print("\n=== Export URL List ===")
    print("[1] PDFs")
    print("[2] Images")
    print("[3] Videos")
    print("[4] Audio")
    print("[5] All")
    print("[0] Back")

    choice = input("\nChoose media: ").strip()

    if choice == "1":
        media_types = ["pdf"]
    elif choice == "2":
        media_types = ["img"]
    elif choice == "3":
        media_types = ["vid"]
    elif choice == "4":
        media_types = ["aud"]
    elif choice == "5":
        media_types = ["pdf", "img", "vid", "aud"]
    else:
        return

    print("\n=== Export Format ===")
    print("[1] Plain URLs")
    print("[2] Numbered for posting")
    print("[0] Back")

    fmt = input("\nChoose format: ").strip()

    if fmt == "1":
        numbered = False
    elif fmt == "2":
        numbered = True
    else:
        return

    index = load_index(cfg)
    export_harvested_urls(cfg, index, media_types, numbered=numbered)


if __name__ == "__main__":
    menu()
