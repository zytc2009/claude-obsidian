from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request

from .base import BaseImporter, ImportResult


class YouTubeImporter(BaseImporter):
    platform = "youtube"
    _OEMBED_API = "https://www.youtube.com/oembed"

    @staticmethod
    def _extract_video_id(url: str) -> str:
        patterns = [
            r"(?:youtube\.com/watch\?.*v=|youtu\.be/)([a-zA-Z0-9_-]{11})",
            r"youtube\.com/embed/([a-zA-Z0-9_-]{11})",
        ]
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return ""

    def _fetch_sync(self, url: str) -> str:
        oembed_url = f"{self._OEMBED_API}?url={urllib.parse.quote(url)}&format=json"
        try:
            req = urllib.request.Request(oembed_url, headers=self.headers)
            with urllib.request.urlopen(req, timeout=15) as resp:  # nosec B310
                oembed = json.loads(resp.read().decode("utf-8"))
        except Exception:
            oembed = {}

        try:
            req = urllib.request.Request(url, headers=self.headers)
            with urllib.request.urlopen(req, timeout=15) as resp:  # nosec B310
                html_content = resp.read().decode("utf-8", errors="replace")
        except Exception:
            html_content = ""

        return json.dumps({"oembed": oembed, "html": html_content})

    def parse_content(self, url: str, text: str) -> ImportResult:
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            data = {}

        oembed = data.get("oembed") or {}
        html_content = data.get("html") or ""

        title = oembed.get("title") or "YouTube 视频"
        author = oembed.get("author_name") or ""
        desc = self._extract_meta(html_content, "og:description") or ""
        video_id = self._extract_video_id(url)

        parts: list[str] = [f"**视频链接：** {url}"]
        if desc:
            parts.append(f"**视频描述：**\n{desc}")
        if author:
            parts.append(f"**频道：** {author}")
        if video_id:
            parts.append(f"**视频ID：** {video_id}")

        content = "\n\n".join(parts)
        summary = desc[:200] if desc else f"YouTube 视频：{title}"

        metadata: dict = {}
        if author:
            metadata["author"] = author

        return ImportResult(
            title=title,
            content=content,
            summary=summary,
            platform=self.platform,
            source_url=url,
            metadata=metadata,
        )
