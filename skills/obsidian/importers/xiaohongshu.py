from __future__ import annotations

import json
import re
from urllib.parse import urlparse

from .base import BaseImporter, ImportResult


class XiaohongshuImporter(BaseImporter):
    platform = "xiaohongshu"

    @staticmethod
    def _extract_initial_state(text: str) -> dict:
        patterns = [
            r"window\.__INITIAL_STATE__\s*=\s*(\{.*?\})\s*;",
            r"window\.__NUXT__\s*=\s*(\{.*?\})\s*;",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.I | re.S)
            if not match:
                continue
            candidate = match.group(1)
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                continue
        return {}

    @staticmethod
    def _extract_title(text: str, state: dict) -> str:
        for key in ("og:title", "twitter:title"):
            meta = BaseImporter._extract_meta(text, key)
            if meta:
                return meta
        for key in ("title", "noteTitle", "desc"):
            value = XiaohongshuImporter._find_first_string(state, key)
            if value:
                return value
        match = re.search(r"<title>(.*?)</title>", text, flags=re.I | re.S)
        if match:
            title = BaseImporter._strip_tags(match.group(1))
            if title:
                return title
        return ""

    @staticmethod
    def _find_first_string(value, wanted_key: str) -> str:
        if isinstance(value, dict):
            if wanted_key in value and isinstance(value[wanted_key], str):
                return value[wanted_key].strip()
            for nested in value.values():
                found = XiaohongshuImporter._find_first_string(nested, wanted_key)
                if found:
                    return found
        elif isinstance(value, list):
            for item in value:
                found = XiaohongshuImporter._find_first_string(item, wanted_key)
                if found:
                    return found
        return ""

    def parse_content(self, url: str, text: str) -> ImportResult:
        state = self._extract_initial_state(text)
        title = self._extract_title(text, state) or urlparse(url).path.rsplit("/", 1)[-1] or "Xiaohongshu Note"
        body = ""
        for key in ("content", "desc", "noteContent", "detail"):
            body = self._find_first_string(state, key)
            if body:
                break
        if not body:
            meta = BaseImporter._extract_meta(text, "og:description")
            if meta:
                body = meta
        if not body:
            body = BaseImporter._strip_tags(text)
        summary = body[:200]
        metadata = {}
        author = self._find_first_string(state, "nickname") or self._find_first_string(state, "author")
        if author:
            metadata["author"] = author
        return ImportResult(
            title=title,
            content=body,
            summary=summary,
            platform=self.platform,
            source_url=url,
            metadata=metadata,
        )

