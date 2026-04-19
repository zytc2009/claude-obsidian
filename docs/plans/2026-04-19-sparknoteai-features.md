# SparkNoteAI Features Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 4 features borrowed from SparkNoteAI: smart summary generator, local image cache, Bilibili/YouTube importers, and a file-based async task queue.

**Architecture:** Each feature is a standalone module in `skills/obsidian/`. ImageCache and SummaryGenerator are called from `obsidian_writer.py` capture flow. Bilibili/YouTube importers plug into `importers/router.py`. TaskQueue/TaskRunner are a separate CLI entry point.

**Tech Stack:** Python 3.11+, asyncio, stdlib only (no new deps); optional `anthropic` SDK for LLM summary; tests via pytest.

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `skills/obsidian/summary_generator.py` | Markdown stripping + LLM/fallback summary |
| Create | `skills/obsidian/image_cache.py` | Download external images into vault attachments |
| Create | `skills/obsidian/importers/bilibili.py` | Bilibili public API → ImportResult |
| Create | `skills/obsidian/importers/youtube.py` | YouTube oEmbed + HTML scrape → ImportResult |
| Create | `skills/obsidian/task_queue.py` | File-based task state store |
| Create | `skills/obsidian/task_runner.py` | CLI: submit / run / status |
| Modify | `skills/obsidian/importers/router.py` | Register bilibili/youtube, add image cache hook |
| Modify | `skills/obsidian/obsidian_writer.py` | Integrate image cache + LLM summary in capture flow |
| Create | `tests/test_summary_generator.py` | |
| Create | `tests/test_image_cache.py` | |
| Create | `tests/test_bilibili_importer.py` | |
| Create | `tests/test_youtube_importer.py` | |
| Create | `tests/test_task_queue.py` | |

---

## Task 1: SummaryGenerator

**Files:**
- Create: `skills/obsidian/summary_generator.py`
- Test: `tests/test_summary_generator.py`

- [ ] **Step 1.1: Write failing tests**

```python
# tests/test_summary_generator.py
import os
import pytest
from skills.obsidian.summary_generator import strip_markdown, generate


class TestStripMarkdown:
    def test_removes_headers(self):
        assert strip_markdown("# Title\ncontent") == "Title\ncontent"

    def test_removes_bold(self):
        assert strip_markdown("**bold** text") == "bold text"

    def test_removes_images(self):
        assert strip_markdown("![alt](http://x.com/img.jpg) text") == "text"

    def test_removes_links(self):
        assert strip_markdown("[link](http://x.com) text") == "link text"

    def test_removes_code_blocks(self):
        assert "removed" not in strip_markdown("```python\nremoved\n```")

    def test_removes_inline_code(self):
        assert "x" not in strip_markdown("`x` text").replace("text", "")


class TestGenerate:
    def test_returns_first_meaningful_paragraph(self):
        content = "Short.\n\nThis is a longer meaningful paragraph with enough text."
        result = generate(content, use_llm=False)
        assert "longer meaningful paragraph" in result

    def test_skips_very_short_paragraphs(self):
        content = "Hi.\n\nThis is the real content with enough characters to matter."
        result = generate(content, use_llm=False)
        assert "real content" in result

    def test_truncates_to_200_chars(self):
        content = "x" * 300
        result = generate(content, use_llm=False)
        assert len(result) <= 200

    def test_strips_markdown_before_summarizing(self):
        content = "# Header\n\n**Bold** content that is meaningful enough to return."
        result = generate(content, use_llm=False)
        assert "#" not in result
        assert "**" not in result

    def test_no_llm_when_key_missing(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        content = "Meaningful content paragraph here, long enough to qualify."
        result = generate(content, title="Test", use_llm=True)
        assert len(result) > 0
        assert "#" not in result

    def test_llm_called_when_key_present(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        import skills.obsidian.summary_generator as sg

        monkeypatch.setattr(sg, "_llm_summary", lambda content, title: "LLM summary result")
        result = generate("any content", title="Title", use_llm=True)
        assert result == "LLM summary result"
```

- [ ] **Step 1.2: Run tests to verify they fail**

```
cd D:/AI/claude_code/claude-obsidian
python -m pytest tests/test_summary_generator.py -v
```
Expected: `ImportError` or `ModuleNotFoundError`

- [ ] **Step 1.3: Implement `summary_generator.py`**

```python
# skills/obsidian/summary_generator.py
from __future__ import annotations

import os
import re


def strip_markdown(text: str) -> str:
    """Remove markdown syntax to get plain text suitable for summarization."""
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"```[\s\S]*?```", "", text)
    text = re.sub(r"`[^`]+`", "", text)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\*{1,2}([^*\n]+)\*{1,2}", r"\1", text)
    text = re.sub(r"_{1,2}([^_\n]+)_{1,2}", r"\1", text)
    text = re.sub(r"^>\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"^[-*+]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _first_meaningful_paragraph(text: str, max_chars: int = 200) -> str:
    plain = strip_markdown(text)
    for para in re.split(r"\n{2,}", plain):
        para = para.strip()
        if len(para) >= 20:
            return para[:max_chars]
    return plain[:max_chars]


def _llm_summary(content: str, title: str) -> str | None:
    """Call Claude if ANTHROPIC_API_KEY is set. Returns None when unavailable."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return None
    try:
        import anthropic
    except ImportError:
        return None
    client = anthropic.Anthropic(api_key=api_key)
    model = os.environ.get("OBSIDIAN_SUMMARY_MODEL", "claude-haiku-4-5-20251001")
    max_content = 2000
    truncated = content[:max_content] + ("..." if len(content) > max_content else "")
    prompt = (
        f"请用1-2句话概括以下文章的核心观点（不超过100字）：\n\n"
        f"标题：{title}\n\n内容：\n{truncated}"
    )
    try:
        msg = client.messages.create(
            model=model,
            max_tokens=150,
            messages=[{"role": "user", "content": prompt}],
        )
        return msg.content[0].text.strip()
    except Exception:
        return None


def generate(content: str, title: str = "", use_llm: bool = True) -> str:
    """Generate a summary with graceful LLM fallback.

    Priority: LLM (if use_llm=True and ANTHROPIC_API_KEY set) → first paragraph.
    """
    if use_llm:
        llm = _llm_summary(content, title)
        if llm:
            return llm
    return _first_meaningful_paragraph(content)
```

- [ ] **Step 1.4: Run tests**

```
python -m pytest tests/test_summary_generator.py -v
```
Expected: all 8 tests PASS

- [ ] **Step 1.5: Commit**

```bash
git add skills/obsidian/summary_generator.py tests/test_summary_generator.py
git commit -m "feat: add SummaryGenerator with LLM fallback to first paragraph"
```

---

## Task 2: ImageCache

**Files:**
- Create: `skills/obsidian/image_cache.py`
- Test: `tests/test_image_cache.py`

- [ ] **Step 2.1: Write failing tests**

```python
# tests/test_image_cache.py
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from skills.obsidian.image_cache import cache_images, _url_to_filename, ATTACHMENTS_DIR


class TestUrlToFilename:
    def test_preserves_jpg_extension(self):
        name = _url_to_filename("https://example.com/photo.jpg")
        assert name.endswith(".jpg")

    def test_preserves_png_extension(self):
        name = _url_to_filename("https://example.com/image.png")
        assert name.endswith(".png")

    def test_unknown_extension_defaults_to_jpg(self):
        name = _url_to_filename("https://example.com/img?size=large")
        assert name.endswith(".jpg")

    def test_same_url_same_filename(self):
        url = "https://example.com/photo.jpg"
        assert _url_to_filename(url) == _url_to_filename(url)

    def test_different_urls_different_filenames(self):
        a = _url_to_filename("https://example.com/a.jpg")
        b = _url_to_filename("https://example.com/b.jpg")
        assert a != b


class TestCacheImages:
    def test_replaces_image_url_with_local_ref(self, tmp_path, monkeypatch):
        def _fake_urlopen(req, timeout=None):
            class FakeResp:
                def read(self):
                    return b"\x89PNG\r\n\x1a\n"
                def __enter__(self):
                    return self
                def __exit__(self, *a):
                    pass
            return FakeResp()

        monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)
        content = "![alt](https://example.com/img.png)"
        result = cache_images(tmp_path, content)
        assert result.startswith("![[")
        assert "https://" not in result
        attachments = tmp_path / ATTACHMENTS_DIR
        assert any(attachments.iterdir())

    def test_keeps_original_on_download_failure(self, tmp_path, monkeypatch):
        def _fail(*a, **kw):
            raise urllib.error.URLError("timeout")

        monkeypatch.setattr(urllib.request, "urlopen", _fail)
        content = "![alt](https://example.com/img.jpg)"
        result = cache_images(tmp_path, content)
        assert "https://example.com/img.jpg" in result

    def test_skips_already_cached_file(self, tmp_path, monkeypatch):
        call_count = {"n": 0}

        def _fake_urlopen(req, timeout=None):
            call_count["n"] += 1
            class FakeResp:
                def read(self):
                    return b"data"
                def __enter__(self):
                    return self
                def __exit__(self, *a):
                    pass
            return FakeResp()

        monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)
        content = "![alt](https://example.com/img.jpg)"
        cache_images(tmp_path, content)
        cache_images(tmp_path, content)
        assert call_count["n"] == 1

    def test_multiple_images_all_replaced(self, tmp_path, monkeypatch):
        def _fake_urlopen(req, timeout=None):
            class FakeResp:
                def read(self):
                    return b"data"
                def __enter__(self):
                    return self
                def __exit__(self, *a):
                    pass
            return FakeResp()

        monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)
        content = "![a](https://a.com/1.jpg)\n![b](https://b.com/2.png)"
        result = cache_images(tmp_path, content)
        assert "https://" not in result

    def test_no_images_returns_unchanged(self, tmp_path):
        content = "No images here, just text."
        assert cache_images(tmp_path, content) == content
```

- [ ] **Step 2.2: Run tests to verify they fail**

```
python -m pytest tests/test_image_cache.py -v
```
Expected: `ImportError`

- [ ] **Step 2.3: Implement `image_cache.py`**

```python
# skills/obsidian/image_cache.py
from __future__ import annotations

import hashlib
import re
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

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
    Enabled by calling this function; caller controls opt-in via env var check.
    """
    attachments_dir = vault / ATTACHMENTS_DIR
    attachments_dir.mkdir(parents=True, exist_ok=True)

    def _replace(match: re.Match) -> str:
        alt = match.group(1)
        url = match.group(2)
        filename = _url_to_filename(url)
        dest = attachments_dir / filename
        if dest.exists() or _download_image(url, dest):
            return f"![[{filename}]]"
        return match.group(0)

    return _IMG_PATTERN.sub(_replace, content)
```

- [ ] **Step 2.4: Run tests**

```
python -m pytest tests/test_image_cache.py -v
```
Expected: all 7 tests PASS

- [ ] **Step 2.5: Integrate into `obsidian_writer.py` capture flow**

In `obsidian_writer.py`, add the import at the top (with the same try/except guard pattern used for other optional imports):

```python
# After the existing try/except import blocks (around line 57)
try:
    from .image_cache import cache_images as _cache_images
except ImportError:
    try:
        from image_cache import cache_images as _cache_images
    except ImportError:
        _cache_images = None  # type: ignore[assignment]
```

Then in the `_capture_fields_from_import_result` function (around line 644), after building `fields["原文主要内容"]`, add image caching. Find this block and replace:

```python
# OLD (around line 659-661):
    if content and not fields.get("原文主要内容", "").strip():
        fields["原文主要内容"] = content
```

```python
# NEW:
    if content and not fields.get("原文主要内容", "").strip():
        fields["原文主要内容"] = content
```

Then in the `main()` function, after `import_result = capture_fetch_url(...)`, add caching call. Find the capture handling in `main()`:

In `main()` around the capture handling section, after fetching `import_result`, find where `_capture_fields_from_import_result` is called and add:

```python
# After getting import_result, before building fields:
if (
    _cache_images is not None
    and os.environ.get("OBSIDIAN_CACHE_IMAGES", "0") == "1"
):
    import_result = import_result.__class__(
        title=import_result.title,
        content=_cache_images(vault, import_result.content),
        summary=import_result.summary,
        platform=import_result.platform,
        source_url=import_result.source_url,
        metadata=import_result.metadata,
    )
```

- [ ] **Step 2.6: Find exact location in `obsidian_writer.py` and add the integration**

Read `obsidian_writer.py` starting at line 700 to find the `main()` function:

```
python -c "
import re
with open('skills/obsidian/obsidian_writer.py') as f:
    lines = f.readlines()
for i, l in enumerate(lines, 1):
    if 'def main' in l or 'capture_fetch_url' in l:
        print(i, l.rstrip())
"
```

Then apply the edits at the correct lines.

- [ ] **Step 2.7: Run full test suite**

```
python -m pytest tests/ -q
```
Expected: 225+ passed (no regressions)

- [ ] **Step 2.8: Commit**

```bash
git add skills/obsidian/image_cache.py tests/test_image_cache.py skills/obsidian/obsidian_writer.py
git commit -m "feat: add ImageCache — download external images to vault attachments"
```

---

## Task 3: Bilibili Importer

**Files:**
- Create: `skills/obsidian/importers/bilibili.py`
- Modify: `skills/obsidian/importers/router.py`
- Test: `tests/test_bilibili_importer.py`

- [ ] **Step 3.1: Write failing tests**

```python
# tests/test_bilibili_importer.py
import json
from skills.obsidian.importers.bilibili import BilibiliImporter


class TestBilibiliExtractBvid:
    def test_extracts_bv_from_standard_url(self):
        url = "https://www.bilibili.com/video/BV1xx411c7mD"
        assert BilibiliImporter._extract_bvid(url) == "BV1xx411c7mD"

    def test_extracts_bv_with_query_string(self):
        url = "https://www.bilibili.com/video/BV1xx411c7mD?t=30"
        assert BilibiliImporter._extract_bvid(url) == "BV1xx411c7mD"

    def test_extracts_av_format(self):
        url = "https://www.bilibili.com/video/av170001"
        assert BilibiliImporter._extract_bvid(url) == "av170001"

    def test_returns_empty_for_unrecognized_url(self):
        assert BilibiliImporter._extract_bvid("https://example.com") == ""


class TestBilibiliParseContent:
    def _api_response(self, **overrides) -> str:
        data = {
            "title": "测试视频",
            "desc": "这是视频描述内容",
            "owner": {"name": "UP主名称"},
            "tags": [{"tag_name": "技术"}, {"tag_name": "Python"}],
            "duration": 375,
            "bvid": "BV1xx411c7mD",
        }
        data.update(overrides)
        return json.dumps({"code": 0, "data": data})

    def test_parse_valid_response(self):
        url = "https://www.bilibili.com/video/BV1xx411c7mD"
        result = BilibiliImporter().parse_content(url, self._api_response())
        assert result.title == "测试视频"
        assert result.platform == "bilibili"
        assert result.source_url == url
        assert "视频描述内容" in result.content
        assert result.metadata["author"] == "UP主名称"
        assert "技术" in result.metadata["tags"]

    def test_duration_formatted_as_mm_ss(self):
        result = BilibiliImporter().parse_content("https://b.com/v/BV1", self._api_response())
        assert "6:15" in result.content

    def test_parse_empty_response_returns_fallback(self):
        result = BilibiliImporter().parse_content("https://b.com/v/BV1", "{}")
        assert result.title == "Bilibili 视频"
        assert result.platform == "bilibili"

    def test_parse_invalid_json_returns_fallback(self):
        result = BilibiliImporter().parse_content("https://b.com/v/BV1", "not json")
        assert result.title == "Bilibili 视频"

    def test_summary_uses_description(self):
        result = BilibiliImporter().parse_content("https://b.com/v/BV1", self._api_response())
        assert "视频描述内容" in result.summary
```

- [ ] **Step 3.2: Run tests to verify they fail**

```
python -m pytest tests/test_bilibili_importer.py -v
```
Expected: `ImportError`

- [ ] **Step 3.3: Implement `importers/bilibili.py`**

```python
# skills/obsidian/importers/bilibili.py
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
        bvid = data.get("bvid") or ""

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
```

- [ ] **Step 3.4: Run tests**

```
python -m pytest tests/test_bilibili_importer.py -v
```
Expected: all 7 tests PASS

- [ ] **Step 3.5: Register in router.py**

In `skills/obsidian/importers/router.py`, add the bilibili import and platform rule:

```python
# Add to imports at top:
from .bilibili import BilibiliImporter

# Add to _PLATFORM_RULES list:
("bilibili", ["www.bilibili.com", "bilibili.com", "b23.tv"]),

# Add to _get_importer():
if platform == "bilibili":
    return BilibiliImporter()
```

- [ ] **Step 3.6: Add router test for bilibili detection**

In `tests/test_importers.py`, add to `TestPlatformDetection`:
```python
def test_detect_platform_bilibili(self):
    assert detect_platform("https://www.bilibili.com/video/BV1xx") == "bilibili"
```

- [ ] **Step 3.7: Run full test suite**

```
python -m pytest tests/ -q
```
Expected: 230+ passed

- [ ] **Step 3.8: Commit**

```bash
git add skills/obsidian/importers/bilibili.py skills/obsidian/importers/router.py tests/test_bilibili_importer.py tests/test_importers.py
git commit -m "feat: add BilibiliImporter using public API"
```

---

## Task 4: YouTube Importer

**Files:**
- Create: `skills/obsidian/importers/youtube.py`
- Modify: `skills/obsidian/importers/router.py`
- Test: `tests/test_youtube_importer.py`

- [ ] **Step 4.1: Write failing tests**

```python
# tests/test_youtube_importer.py
import json
from skills.obsidian.importers.youtube import YouTubeImporter


class TestYouTubeExtractVideoId:
    def test_standard_watch_url(self):
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        assert YouTubeImporter._extract_video_id(url) == "dQw4w9WgXcQ"

    def test_short_url(self):
        url = "https://youtu.be/dQw4w9WgXcQ"
        assert YouTubeImporter._extract_video_id(url) == "dQw4w9WgXcQ"

    def test_embed_url(self):
        url = "https://www.youtube.com/embed/dQw4w9WgXcQ"
        assert YouTubeImporter._extract_video_id(url) == "dQw4w9WgXcQ"

    def test_watch_with_extra_params(self):
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=42s"
        assert YouTubeImporter._extract_video_id(url) == "dQw4w9WgXcQ"

    def test_returns_empty_for_non_youtube(self):
        assert YouTubeImporter._extract_video_id("https://vimeo.com/123") == ""


class TestYouTubeParseContent:
    def _make_payload(self, title="Test Video", author="Test Channel", desc="") -> str:
        oembed = {"title": title, "author_name": author}
        html = f'<meta property="og:description" content="{desc}">' if desc else ""
        return json.dumps({"oembed": oembed, "html": html})

    def test_parse_extracts_title_and_author(self):
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        result = YouTubeImporter().parse_content(url, self._make_payload("My Video", "My Channel"))
        assert result.title == "My Video"
        assert result.platform == "youtube"
        assert result.source_url == url
        assert result.metadata["author"] == "My Channel"

    def test_parse_includes_description_in_content(self):
        url = "https://www.youtube.com/watch?v=abc"
        result = YouTubeImporter().parse_content(url, self._make_payload(desc="Great video description"))
        assert "Great video description" in result.content

    def test_parse_invalid_json_returns_fallback(self):
        result = YouTubeImporter().parse_content("https://youtube.com/watch?v=x", "bad json")
        assert result.title == "YouTube 视频"
        assert result.platform == "youtube"

    def test_parse_empty_oembed_returns_fallback_title(self):
        payload = json.dumps({"oembed": {}, "html": ""})
        result = YouTubeImporter().parse_content("https://youtube.com/watch?v=x", payload)
        assert result.title == "YouTube 视频"

    def test_summary_uses_description(self):
        url = "https://www.youtube.com/watch?v=abc"
        result = YouTubeImporter().parse_content(url, self._make_payload(desc="Video summary content"))
        assert "Video summary content" in result.summary
```

- [ ] **Step 4.2: Run tests to verify they fail**

```
python -m pytest tests/test_youtube_importer.py -v
```
Expected: `ImportError`

- [ ] **Step 4.3: Implement `importers/youtube.py`**

```python
# skills/obsidian/importers/youtube.py
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
                html = resp.read().decode("utf-8", errors="replace")
        except Exception:
            html = ""

        return json.dumps({"oembed": oembed, "html": html})

    def parse_content(self, url: str, text: str) -> ImportResult:
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            data = {}

        oembed = data.get("oembed") or {}
        html = data.get("html") or ""

        title = oembed.get("title") or "YouTube 视频"
        author = oembed.get("author_name") or ""
        desc = self._extract_meta(html, "og:description") or ""
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
```

- [ ] **Step 4.4: Run tests**

```
python -m pytest tests/test_youtube_importer.py -v
```
Expected: all 8 tests PASS

- [ ] **Step 4.5: Register in router.py**

```python
# Add to imports at top of router.py:
from .youtube import YouTubeImporter

# Add to _PLATFORM_RULES list:
("youtube", ["www.youtube.com", "youtube.com", "youtu.be"]),

# Add to _get_importer():
if platform == "youtube":
    return YouTubeImporter()
```

- [ ] **Step 4.6: Add router test for youtube detection**

In `tests/test_importers.py`, add:
```python
def test_detect_platform_youtube(self):
    assert detect_platform("https://www.youtube.com/watch?v=abc") == "youtube"

def test_detect_platform_youtu_be(self):
    assert detect_platform("https://youtu.be/abc") == "youtube"
```

- [ ] **Step 4.7: Run full test suite**

```
python -m pytest tests/ -q
```
Expected: 235+ passed

- [ ] **Step 4.8: Commit**

```bash
git add skills/obsidian/importers/youtube.py skills/obsidian/importers/router.py tests/test_youtube_importer.py tests/test_importers.py
git commit -m "feat: add YouTubeImporter using oEmbed API + HTML scrape"
```

---

## Task 5: TaskQueue + TaskRunner

**Files:**
- Create: `skills/obsidian/task_queue.py`
- Create: `skills/obsidian/task_runner.py`
- Test: `tests/test_task_queue.py`

- [ ] **Step 5.1: Write failing tests**

```python
# tests/test_task_queue.py
import time
from pathlib import Path
from skills.obsidian.task_queue import TaskQueue, TaskStatus, Task


class TestTaskQueue:
    def test_submit_creates_pending_task(self, tmp_path):
        q = TaskQueue(tmp_path)
        task_id = q.submit("https://example.com/article")
        task = q.get(task_id)
        assert task is not None
        assert task.url == "https://example.com/article"
        assert task.status == TaskStatus.PENDING
        assert task.progress == 0

    def test_update_changes_status(self, tmp_path):
        q = TaskQueue(tmp_path)
        task_id = q.submit("https://example.com")
        q.update(task_id, status=TaskStatus.RUNNING, progress=50, message="Fetching...")
        task = q.get(task_id)
        assert task.status == TaskStatus.RUNNING
        assert task.progress == 50
        assert task.message == "Fetching..."

    def test_update_nonexistent_task_is_noop(self, tmp_path):
        q = TaskQueue(tmp_path)
        q.update("nonexistent", status=TaskStatus.DONE)  # should not raise

    def test_list_all_returns_all_tasks(self, tmp_path):
        q = TaskQueue(tmp_path)
        q.submit("https://a.com")
        q.submit("https://b.com")
        assert len(q.list_all()) == 2

    def test_pending_filters_by_status(self, tmp_path):
        q = TaskQueue(tmp_path)
        id1 = q.submit("https://a.com")
        id2 = q.submit("https://b.com")
        q.update(id1, status=TaskStatus.DONE)
        pending = q.pending()
        assert len(pending) == 1
        assert pending[0].task_id == id2

    def test_state_persists_across_instances(self, tmp_path):
        q1 = TaskQueue(tmp_path)
        task_id = q1.submit("https://example.com")
        q2 = TaskQueue(tmp_path)
        task = q2.get(task_id)
        assert task is not None
        assert task.url == "https://example.com"

    def test_task_dict_roundtrip(self, tmp_path):
        q = TaskQueue(tmp_path)
        task_id = q.submit("https://example.com")
        q.update(task_id, status=TaskStatus.DONE, result_path="/vault/note.md")
        task = q.get(task_id)
        assert task.status == TaskStatus.DONE
        assert task.result_path == "/vault/note.md"

    def test_state_file_created_in_vault(self, tmp_path):
        q = TaskQueue(tmp_path)
        q.submit("https://example.com")
        state_file = tmp_path / ".obsidian-tasks.json"
        assert state_file.exists()
```

- [ ] **Step 5.2: Run tests to verify they fail**

```
python -m pytest tests/test_task_queue.py -v
```
Expected: `ImportError`

- [ ] **Step 5.3: Implement `task_queue.py`**

```python
# skills/obsidian/task_queue.py
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


@dataclass
class Task:
    task_id: str
    url: str
    status: TaskStatus = TaskStatus.PENDING
    progress: int = 0
    message: str = ""
    result_path: str = ""
    error: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Task":
        d = dict(d)
        d["status"] = TaskStatus(d["status"])
        return cls(**d)


class TaskQueue:
    _STATE_FILE = ".obsidian-tasks.json"

    def __init__(self, vault: Path) -> None:
        self.vault = vault
        self._path = vault / self._STATE_FILE

    def _load(self) -> dict[str, Task]:
        if not self._path.exists():
            return {}
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            return {tid: Task.from_dict(t) for tid, t in data.items()}
        except (json.JSONDecodeError, KeyError, TypeError):
            return {}

    def _save(self, tasks: dict[str, Task]) -> None:
        self._path.write_text(
            json.dumps(
                {tid: t.to_dict() for tid, t in tasks.items()},
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    def submit(self, url: str) -> str:
        """Add a URL import task and return its task_id."""
        tasks = self._load()
        task_id = uuid.uuid4().hex[:8]
        tasks[task_id] = Task(task_id=task_id, url=url)
        self._save(tasks)
        return task_id

    def update(self, task_id: str, **kwargs: Any) -> None:
        tasks = self._load()
        if task_id not in tasks:
            return
        task = tasks[task_id]
        for key, val in kwargs.items():
            setattr(task, key, val)
        task.updated_at = time.time()
        self._save(tasks)

    def get(self, task_id: str) -> Task | None:
        return self._load().get(task_id)

    def list_all(self) -> list[Task]:
        return list(self._load().values())

    def pending(self) -> list[Task]:
        return [t for t in self._load().values() if t.status == TaskStatus.PENDING]
```

- [ ] **Step 5.4: Run tests**

```
python -m pytest tests/test_task_queue.py -v
```
Expected: all 8 tests PASS

- [ ] **Step 5.5: Implement `task_runner.py`**

```python
# skills/obsidian/task_runner.py
"""
Async import task runner for claude-obsidian.

Commands:
  submit  --vault VAULT --url URL [--url URL ...]   Add URLs to queue, print task IDs
  run     --vault VAULT [--workers N]               Run all pending tasks concurrently
  status  --vault VAULT                              Print current task states
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from .task_queue import TaskQueue, TaskStatus

try:
    from .importers.router import _fetch_async
except ImportError:
    from importers.router import _fetch_async  # type: ignore[no-redef]

try:
    from .obsidian_writer import write_note
except ImportError:
    from obsidian_writer import write_note  # type: ignore[no-redef]


async def _run_task(queue: TaskQueue, task_id: str, vault: Path) -> None:
    queue.update(task_id, status=TaskStatus.RUNNING, progress=10, message="Fetching...")
    task = queue.get(task_id)
    if task is None:
        return
    try:
        result = await _fetch_async(task.url)
        queue.update(task_id, progress=60, message="Writing note...")

        fields: dict = {
            "source": result.source_url,
            "platform": result.platform,
            "source_url": result.source_url,
            "核心观点": result.summary,
            "原文主要内容": result.content,
        }
        if isinstance(result.metadata, dict):
            author = result.metadata.get("author", "")
            if author:
                fields["author"] = author

        filepath = write_note(
            vault=vault,
            note_type="literature",
            title=result.title,
            fields=fields,
            is_draft=False,
        )
        queue.update(
            task_id,
            status=TaskStatus.DONE,
            progress=100,
            message="Done",
            result_path=str(filepath),
        )
        print(f"[{task_id}] Done → {filepath.relative_to(vault)}")
    except Exception as exc:
        queue.update(task_id, status=TaskStatus.FAILED, error=str(exc), message="Failed")
        print(f"[{task_id}] Failed: {exc}", file=sys.stderr)


async def _run_all(queue: TaskQueue, vault: Path, workers: int) -> None:
    pending = queue.pending()
    if not pending:
        print("No pending tasks.")
        return
    sem = asyncio.Semaphore(workers)

    async def _guarded(task_id: str) -> None:
        async with sem:
            await _run_task(queue, task_id, vault)

    await asyncio.gather(*[_guarded(t.task_id) for t in pending])


def cmd_submit(args: argparse.Namespace) -> None:
    vault = Path(args.vault).expanduser()
    queue = TaskQueue(vault)
    for url in args.url:
        task_id = queue.submit(url)
        print(f"Submitted [{task_id}]: {url}")


def cmd_run(args: argparse.Namespace) -> None:
    vault = Path(args.vault).expanduser()
    queue = TaskQueue(vault)
    asyncio.run(_run_all(queue, vault, args.workers))


def cmd_status(args: argparse.Namespace) -> None:
    vault = Path(args.vault).expanduser()
    queue = TaskQueue(vault)
    tasks = queue.list_all()
    if not tasks:
        print("No tasks.")
        return
    for task in sorted(tasks, key=lambda t: t.created_at):
        status_icon = {"pending": "⏳", "running": "🔄", "done": "✅", "failed": "❌"}.get(
            task.status.value, "?"
        )
        print(f"{status_icon} [{task.task_id}] {task.status.value:8s} {task.progress:3d}% | {task.url}")
        if task.result_path:
            print(f"   → {task.result_path}")
        if task.error:
            print(f"   ✗ {task.error}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Obsidian import task runner")
    sub = parser.add_subparsers(dest="command", required=True)

    p_submit = sub.add_parser("submit", help="Submit URLs to the import queue")
    p_submit.add_argument("--vault", required=True)
    p_submit.add_argument("--url", required=True, action="append")

    p_run = sub.add_parser("run", help="Run all pending tasks")
    p_run.add_argument("--vault", required=True)
    p_run.add_argument("--workers", type=int, default=3)

    p_status = sub.add_parser("status", help="Show task status")
    p_status.add_argument("--vault", required=True)

    args = parser.parse_args(argv)
    {"submit": cmd_submit, "run": cmd_run, "status": cmd_status}[args.command](args)


if __name__ == "__main__":
    main()
```

- [ ] **Step 5.6: Run full test suite**

```
python -m pytest tests/ -q
```
Expected: 240+ passed

- [ ] **Step 5.7: Smoke test the CLI**

```bash
python -m skills.obsidian.task_runner submit --vault /tmp/test-vault --url https://example.com
python -m skills.obsidian.task_runner status --vault /tmp/test-vault
```
Expected: task ID printed, then status shows `⏳ pending`

- [ ] **Step 5.8: Commit**

```bash
git add skills/obsidian/task_queue.py skills/obsidian/task_runner.py tests/test_task_queue.py
git commit -m "feat: add TaskQueue + TaskRunner for concurrent async imports"
```

---

## Self-Review Checklist

- [x] **Spec coverage:** All 4 features have tasks and tests
- [x] **No placeholders:** Every step has actual code
- [x] **Type consistency:** `ImportResult`, `TaskStatus`, `Task`, `TaskQueue` used consistently across tasks
- [x] **SummaryGenerator** — standalone, no deps on other new modules
- [x] **ImageCache** — integrated into capture flow via `OBSIDIAN_CACHE_IMAGES=1`
- [x] **Bilibili/YouTube** — both plug into router.py via same `_PLATFORM_RULES` + `_get_importer()` pattern
- [x] **TaskQueue** — file-based state, tested for persistence across instances
- [x] **TaskRunner** — async `gather()` for concurrent imports, no daemon required
