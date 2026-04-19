from __future__ import annotations

import hashlib
import re
import urllib.request
from pathlib import Path

ATTACHMENTS_DIR = "07-Attachments"
_IMG_PATTERN = re.compile(r"!\[([^\]]*)\]\((https?://[^)\s]+)\)")
_VALID_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".bmp"}


def _url_to_filename(url: str) -> str:
    url_hash = hashlib.md5(url.encode()).hexdigest()[:8]  # nosec B324
    path_part = url.split("?")[0].rstrip("/")
    ext = Path(path_part).suffix.lower()
    if ext not in _VALID_EXTS:
        ext = ".jpg"
    return f"img_{url_hash}{ext}"


def _download_image(url: str, dest: Path) -> bool:
    headers = {"User-Agent": "Mozilla/5.0 (compatible; ObsidianCapture/1.0)"}
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:  # nosec B310
            data = resp.read()
        dest.write_bytes(data)
        return True
    except Exception:
        return False


def cache_images(vault: Path, content: str) -> str:
    """Replace external image URLs in markdown with local vault references.

    Downloads images to vault/07-Attachments/. Skips on failure (keeps original URL).
    """
    attachments_dir = vault / ATTACHMENTS_DIR
    attachments_dir.mkdir(parents=True, exist_ok=True)

    def _replace(match: re.Match) -> str:
        url = match.group(2)
        filename = _url_to_filename(url)
        dest = attachments_dir / filename
        if dest.exists() or _download_image(url, dest):
            return f"![[{filename}]]"
        return match.group(0)

    return _IMG_PATTERN.sub(_replace, content)
