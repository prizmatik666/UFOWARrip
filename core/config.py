# UFOWARrip
# Created by Prizmatik
# https://github.com/prizmatik666/UFOWARrip

from dataclasses import dataclass, asdict
from pathlib import Path
import json


CONFIG_PATH = Path("warrip_config.json")


@dataclass
class Config:
    start_url: str = "https://www.war.gov/UFO/"
    release: str = "release_1"
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
            base.update(data)
            return cls(**base)

        cfg = cls()
        cfg.save()
        return cfg

    def save(self):
        CONFIG_PATH.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")

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
