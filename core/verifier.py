# UFOWARrip
# Created by Prizmatik
# https://github.com/prizmatik666/UFOWARrip

from core.index_store import load_index, save_index
from core.downloader import sha256_file


def verify_downloads(cfg):
    cfg.ensure_dirs()
    index = load_index(cfg)
    records = index.get("records", {})

    present = 0
    missing = []

    for asset, rec in sorted(records.items()):
        path = cfg.downloads_dir / f"{asset.lower()}.pdf"
        dl = rec.setdefault("download", {})

        if path.exists() and path.stat().st_size > 0:
            present += 1
            dl.update({
                "downloaded": True,
                "path": str(path),
                "status": "verified",
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            })
        else:
            missing.append(asset)
            dl.update({
                "downloaded": False,
                "status": "missing",
            })

    save_index(cfg, index)

    print(f"[✓] Present: {present}")
    print(f"[!] Missing: {len(missing)}")
