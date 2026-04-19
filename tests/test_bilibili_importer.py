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
