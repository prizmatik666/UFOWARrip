# UFOWARrip
# Created by Prizmatik
# https://github.com/prizmatik666/UFOWARrip

from dataclasses import dataclass, asdict
from pathlib import Path
import json
import re


CONFIG_PATH = Path("warrip_config.json")
RELEASE_URL_TEMPLATE = "https://www.war.gov/UFO/?releaseDate=Release+{release_num:02d}#records"


def release_label(release_number: int) -> str:
    return f"release_{int(release_number)}"


def release_number_from_label(value: str) -> int:
    match = re.search(r"(\d+)", value or "")
    return int(match.group(1)) if match else 1


def release_url(release_number: int) -> str:
    return RELEASE_URL_TEMPLATE.format(release_num=int(release_number))


@dataclass
class Config:
    start_url: str = "https://www.war.gov/UFO/?releaseDate=Release+01#records"
    release: str = "release_1"
    release_number: int = 1
    output_dir: str = "war_ufo_data"
    headed: bool = True
    stable_wait_ms: int = 1200
    max_pages: int = 30
    download_delay_sec: float = 0.35
    request_timeout_sec: int = 60
    user_agent: str = (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )

    @classmethod
    def load(cls):
        if CONFIG_PATH.exists():
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            base = asdict(cls())
            base.update({k: v for k, v in data.items() if k in base})

            if "release_number" not in data:
                base["release_number"] = release_number_from_label(base.get("release", "release_1"))

            cfg = cls(**base)
            cfg.set_release(cfg.release_number, save=False)
            return cfg

        cfg = cls()
        cfg.save()
        return cfg

    def save(self):
        CONFIG_PATH.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")

    def set_release(self, release_number: int, save=True):
        release_number = int(release_number)
        if release_number < 1:
            raise ValueError("release number must be 1 or greater")

        self.release_number = release_number
        self.release = release_label(release_number)
        self.start_url = release_url(release_number)

        if save:
            self.save()

    @property
    def release_padded(self):
        return f"{self.release_number:02d}"

    @property
    def root(self):
        return Path(self.output_dir)

    @property
    def data_dir(self):
        return self.root / "data"

    @property
    def downloads_dir(self):
        return self.root / "downloads" / self.release

    @property
    def debug_dir(self):
        return self.root / "debug"

    @property
    def profile_dir(self):
        return Path("browser_profile")

    def ensure_dirs(self):
        for p in [
            self.data_dir,
            self.downloads_dir,
            self.root / "logs",
            self.debug_dir / "screenshots",
            self.debug_dir / "html",
            self.debug_dir / "text",
            self.profile_dir,
        ]:
            p.mkdir(parents=True, exist_ok=True)
