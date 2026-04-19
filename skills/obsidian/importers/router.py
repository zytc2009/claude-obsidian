from __future__ import annotations

import asyncio
import json
import re
import sys
from urllib.parse import urlparse

from .base import BaseImporter, ImportResult
from .bilibili import BilibiliImporter
from .wechat import WechatImporter
from .xiaohongshu import XiaohongshuImporter
from .youtube import YouTubeImporter


class GenericImporter(BaseImporter):
    platform = "generic"

    def parse_content(self, url: str, text: str) -> ImportResult:
        title = ""
        match = self._extract_meta(text, "og:title")
        if match:
            title = match
        if not title:
            match = self._extract_meta(text, "title", attr="name")
            if match:
                title = match
        if not title:
            match = re.search(r"<title>(.*?)</title>", text, flags=re.I | re.S)
            if match:
                title = self._strip_tags(match.group(1))
        title = title or urlparse(url).path.rsplit("/", 1)[-1] or "Captured Content"
        content = self._strip_tags(text)
        summary = content[:200]
        return ImportResult(
            title=title,
            content=content,
            summary=summary,
            platform=self.platform,
            source_url=url,
            metadata={},
        )


_PLATFORM_RULES = [
    ("wechat", ["mp.weixin.qq.com"]),
    ("xiaohongshu", ["www.xiaohongshu.com", "xhslink.com", "xiaohongshu.com"]),
    ("bilibili", ["www.bilibili.com", "bilibili.com", "b23.tv"]),
    ("youtube", ["www.youtube.com", "youtube.com", "youtu.be"]),
]


def detect_platform(url: str) -> str:
    host = urlparse(url).netloc.lower()
    for platform, domains in _PLATFORM_RULES:
        if any(domain in host for domain in domains):
            return platform
    return "generic"


def _get_importer(platform: str) -> BaseImporter:
    if platform == "wechat":
        return WechatImporter()
    if platform == "xiaohongshu":
        return XiaohongshuImporter()
    if platform == "bilibili":
        return BilibiliImporter()
    if platform == "youtube":
        return YouTubeImporter()
    return GenericImporter()


async def _fetch_async(url: str) -> ImportResult:
    platform = detect_platform(url)
    importer = _get_importer(platform)
    return await importer.import_from_url(url)


def fetch_url(url: str) -> ImportResult:
    return asyncio.run(_fetch_async(url))


def main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(description="Fetch content from supported platforms")
    parser.add_argument("--url", required=True)
    args = parser.parse_args(argv)

    result = fetch_url(args.url)
    print(
        json.dumps(
            {
                "title": result.title,
                "content": result.content,
                "summary": result.summary,
                "platform": result.platform,
                "source_url": result.source_url,
                "metadata": result.metadata or {},
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
