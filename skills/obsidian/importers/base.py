from __future__ import annotations

import asyncio
import html
import re
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ImportResult:
    title: str
    content: str
    summary: str
    platform: str
    source_url: str
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseImporter(ABC):
    platform = "generic"

    def __init__(self, headers: dict[str, str] | None = None):
        self.headers = headers or {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            )
        }

    async def import_from_url(self, url: str) -> ImportResult:
        text = await self.fetch_content(url)
        return self.parse_content(url, text)

    async def fetch_content(self, url: str) -> str:
        return await asyncio.to_thread(self._fetch_sync, url)

    def _fetch_sync(self, url: str) -> str:
        request = urllib.request.Request(url, headers=self.headers)
        with urllib.request.urlopen(request, timeout=20) as response:  # nosec B310
            raw = response.read()
            charset = response.headers.get_content_charset() or "utf-8"
        return raw.decode(charset, errors="replace")

    @abstractmethod
    def parse_content(self, url: str, text: str) -> ImportResult:
        raise NotImplementedError

    @staticmethod
    def _strip_tags(text: str) -> str:
        cleaned = re.sub(r"(?is)<script.*?>.*?</script>", " ", text)
        cleaned = re.sub(r"(?is)<style.*?>.*?</style>", " ", cleaned)
        cleaned = re.sub(r"(?s)<[^>]+>", " ", cleaned)
        cleaned = html.unescape(cleaned)
        cleaned = re.sub(r"[ \t\r\f\v]+", " ", cleaned)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        return cleaned.strip()

    @staticmethod
    def _extract_meta(text: str, key: str, attr: str = "property") -> str:
        pattern = rf'<meta[^>]+{attr}=["\']{re.escape(key)}["\'][^>]+content=["\']([^"\']+)["\']'
        match = re.search(pattern, text, flags=re.I)
        return html.unescape(match.group(1).strip()) if match else ""

