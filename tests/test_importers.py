from skills.obsidian.importers.router import GenericImporter, detect_platform
from skills.obsidian.importers.wechat import WechatImporter
from skills.obsidian.importers.xiaohongshu import XiaohongshuImporter


class TestPlatformDetection:
    def test_detect_platform_wechat(self):
        assert detect_platform("https://mp.weixin.qq.com/s/abc") == "wechat"

    def test_detect_platform_xiaohongshu(self):
        assert detect_platform("https://www.xiaohongshu.com/explore/abc") == "xiaohongshu"

    def test_detect_platform_generic(self):
        assert detect_platform("https://example.com") == "generic"

    def test_detect_platform_bilibili(self):
        assert detect_platform("https://www.bilibili.com/video/BV1xx") == "bilibili"

    def test_detect_platform_youtube(self):
        assert detect_platform("https://www.youtube.com/watch?v=abc") == "youtube"

    def test_detect_platform_youtu_be(self):
        assert detect_platform("https://youtu.be/abc") == "youtube"


class TestWechatImporter:
    def test_parse_content_extracts_title_body_and_summary(self):
        html = """
        <html>
          <head><title>Fallback title</title></head>
          <body>
            <h1 id="activity-name">微信文章标题</h1>
            <div id="js_content"><p>第一段内容</p><p>第二段内容</p></div>
          </body>
        </html>
        """
        result = WechatImporter().parse_content("https://mp.weixin.qq.com/s/test", html)
        assert result.platform == "wechat"
        assert result.title == "微信文章标题"
        assert "第一段内容" in result.content
        assert result.summary == "第一段内容 第二段内容"


class TestXiaohongshuImporter:
    def test_parse_content_uses_meta_fallback(self):
        html = """
        <html>
          <head>
            <meta property="og:title" content="小红书标题">
            <meta property="og:description" content="小红书摘要内容">
          </head>
          <body>
            <script>window.__INITIAL_STATE__ = {"note": {"author": {"nickname": "Alice"}}};</script>
          </body>
        </html>
        """
        result = XiaohongshuImporter().parse_content("https://www.xiaohongshu.com/explore/test", html)
        assert result.platform == "xiaohongshu"
        assert result.title == "小红书标题"
        assert "小红书摘要内容" in result.content
        assert result.summary == "小红书摘要内容"
        assert result.metadata["author"] == "Alice"


class TestGenericImporter:
    def test_parse_content_strips_html(self):
        html = "<html><head><title>Generic Title</title></head><body><p>Hello <b>world</b></p></body></html>"
        result = GenericImporter().parse_content("https://example.com/path", html)
        assert result.platform == "generic"
        assert result.title == "Generic Title"
        assert "Hello world" in result.content
