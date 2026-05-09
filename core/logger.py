# UFOWARrip
# Created by Prizmatik
# https://github.com/prizmatik666/UFOWARrip

from datetime import datetime, timezone


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def log(cfg, msg: str):
    cfg.ensure_dirs()
    path = cfg.root / "logs" / "warrip.log"
    path.open("a", encoding="utf-8").write(f"[{now_iso()}] {msg}\n")
