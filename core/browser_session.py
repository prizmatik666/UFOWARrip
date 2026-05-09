# UFOWARrip
# Created by Prizmatik
# https://github.com/prizmatik666/UFOWARrip

import os

from playwright.sync_api import sync_playwright


class BrowserSession:
    def __init__(self, cfg):
        self.cfg = cfg
        self.pw = None
        self.context = None
        self.page = None

    def __enter__(self):
        self.cfg.ensure_dirs()
        headless = not self.cfg.headed

        if self.cfg.headed and os.name == "posix" and not os.environ.get("DISPLAY"):
            print("[WarRip] Browser headed=True but no DISPLAY is available; using headless Chromium.")
            headless = True

        try:
            self.pw = sync_playwright().start()

            self.context = self.pw.chromium.launch_persistent_context(
                user_data_dir=str(self.cfg.profile_dir),
                headless=headless,
                ignore_https_errors=True,
                viewport={"width": 1365, "height": 900},
                user_agent=self.cfg.user_agent,
                args=[
                    "--disable-dev-shm-usage",
                    "--no-sandbox",
                    "--disable-crash-reporter",
                    "--disable-crashpad",
                ],
            )

            self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
            return self.page

        except Exception:
            self.close()
            raise

    def __exit__(self, exc_type, exc, tb):
        self.close()

    def close(self):
        if self.context:
            try:
                self.context.close()
            except Exception:
                pass
            finally:
                self.context = None
                self.page = None

        if self.pw:
            try:
                self.pw.stop()
            except Exception:
                pass
            finally:
                self.pw = None
