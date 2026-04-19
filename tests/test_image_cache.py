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
