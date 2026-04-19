from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request

from .base import BaseImporter, ImportResult


class BilibiliImporter(BaseImporter):
    platform = "bilibili"
    _API = "https://api.bilibili.com/x/web-interface/view"

    @staticmethod
    def _extract_bvid(url: str) -> str:
        match = re.search(r"/video/(BV[a-zA-Z0-9]+)", url)
        if match:
            return match.group(1)
        match = re.search(r"/video/av(\d+)", url, re.I)
        if match:
            return f"av{match.group(1)}"
        return ""

    def _fetch_sync(self, url: str) -> str:
        bvid = self._extract_bvid(url)
        if not bvid:
            return "{}"
        if bvid.startswith("BV"):
            params = {"bvid": bvid}
        else:
            params = {"aid": bvid[2:]}
        api_url = f"{self._API}?{urllib.parse.urlencode(params)}"
        headers = {**self.headers, "Referer": "https://www.bilibili.com/"}
        req = urllib.request.Request(api_url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:  # nosec B310
            return resp.read().decode("utf-8")

    def parse_content(self, url: str, text: str) -> ImportResult:
        try:
            data = json.loads(text).get("data") or {}
        except (json.JSONDecodeError, AttributeError):
            data = {}

        title = data.get("title") or "Bilibili 视频"
        desc = data.get("desc") or ""
        owner = (data.get("owner") or {}).get("name", "")
        tags = [t.get("tag_name", "") for t in (data.get("tags") or []) if t.get("tag_name")]
        duration = data.get("duration") or 0

        parts: list[str] = []
        if desc:
            parts.append(f"**视频简介：**\n{desc}")
        if tags:
            parts.append(f"**标签：** {', '.join(tags)}")
        if duration:
            parts.append(f"**时长：** {duration // 60}:{duration % 60:02d}")
        parts.append(f"**视频链接：** {url}")

        content = "\n\n".join(parts)
        summary = desc[:200] if desc else f"B站视频：{title}"

        metadata: dict = {}
        if owner:
            metadata["author"] = owner
        if tags:
            metadata["tags"] = tags

        return ImportResult(
            title=title,
            content=content,
            summary=summary,
            platform=self.platform,
            source_url=url,
            metadata=metadata,
        )
