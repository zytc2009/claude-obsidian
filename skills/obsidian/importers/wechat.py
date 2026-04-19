from __future__ import annotations

import re
from urllib.parse import urlparse

from .base import BaseImporter, ImportResult


class WechatImporter(BaseImporter):
    platform = "wechat"

    @staticmethod
    def _extract_title(text: str) -> str:
        patterns = [
            r'<h1[^>]+id=["\']activity-name["\'][^>]*>(.*?)</h1>',
            r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']',
            r"<title>(.*?)</title>",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.I | re.S)
            if match:
                title = BaseImporter._strip_tags(match.group(1)).strip()
                if title:
                    return title
        return ""

    @staticmethod
    def _extract_body(text: str) -> str:
        match = re.search(r'<div[^>]+id=["\']js_content["\'][^>]*>(.*?)</div>', text, flags=re.I | re.S)
        if match:
            return BaseImporter._strip_tags(match.group(1))
        return BaseImporter._strip_tags(text)

    def parse_content(self, url: str, text: str) -> ImportResult:
        title = self._extract_title(text) or urlparse(url).path.rsplit("/", 1)[-1] or "WeChat Article"
        content = self._extract_body(text)
        summary = ""
        paragraphs = [part.strip() for part in re.split(r"\n+", content) if part.strip()]
        if paragraphs:
            summary = paragraphs[0][:200]
        return ImportResult(
            title=title,
            content=content,
            summary=summary,
            platform=self.platform,
            source_url=url,
            metadata={},
        )

