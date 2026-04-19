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
