from datetime import date

from skills.obsidian.profile_manager import (
    get_profile_path,
    read_profile,
    upsert_profile,
)


class TestProfilePath:
    def test_get_profile_path_creates_parent_directory(self, tmp_path):
        path = get_profile_path(tmp_path, "personal")
        assert path == tmp_path / "05-Profile" / "Profile - Personal.md"
        assert path.parent.exists()


class TestProfileUpsert:
    def test_upsert_creates_profile_from_template_and_increments_version(self, tmp_path):
        path = upsert_profile(
            tmp_path,
            "personal",
            "基本信息",
            "姓名: Alice\n地点: Dubai",
        )
        text = path.read_text(encoding="utf-8")
        assert "type: profile" in text
        assert "subtype: personal" in text
        assert "version: 2" in text
        assert "姓名: Alice" in text
        assert "地点: Dubai" in text

    def test_upsert_log_section_appends_with_date_prefix(self, tmp_path):
        path = upsert_profile(
            tmp_path,
            "preferences",
            "纠正记录",
            "不要在结尾加总结",
        )
        text = path.read_text(encoding="utf-8")
        today = date.today().strftime("%Y-%m-%d")
        assert "不要在结尾加总结" in text
        assert f"[{today}]" in text

    def test_upsert_writing_style_preference_is_not_logged_with_date_prefix(self, tmp_path):
        path = upsert_profile(
            tmp_path,
            "preferences",
            "写作风格偏好",
            "keep answers concise",
        )
        text = path.read_text(encoding="utf-8")
        section = text.split("## 写作风格偏好", 1)[1].split("##", 1)[0]
        assert "keep answers concise" in section
        assert "[" not in section

    def test_upsert_list_section_deduplicates_wikilinks(self, tmp_path):
        path = upsert_profile(
            tmp_path,
            "projects",
            "活跃项目",
            "- [[Project Alpha]]\n- [[Project Beta]]",
        )
        upsert_profile(
            tmp_path,
            "projects",
            "活跃项目",
            "- [[Project Alpha]]\n- [[Project Gamma]]",
        )
        text = path.read_text(encoding="utf-8")
        assert text.count("[[Project Alpha]]") == 1
        assert "[[Project Gamma]]" in text

    def test_upsert_kv_section_keeps_existing_keys(self, tmp_path):
        path = upsert_profile(
            tmp_path,
            "tooling",
            "编程语言",
            "Python: 3.12\nTypeScript: 5",
        )
        upsert_profile(
            tmp_path,
            "tooling",
            "编程语言",
            "Python: 3.13\nRust: 1.80",
        )
        text = path.read_text(encoding="utf-8")
        assert "Python: 3.12" in text
        assert "Python: 3.13" not in text
        assert "Rust: 1.80" in text


class TestProfileRead:
    def test_read_missing_profile_returns_empty_string(self, tmp_path):
        assert read_profile(tmp_path, "personal") == ""

    def test_read_all_profiles_concatenates_existing_notes(self, tmp_path):
        upsert_profile(tmp_path, "personal", "基本信息", "姓名: Alice")
        upsert_profile(tmp_path, "projects", "活跃项目", "- [[Project Alpha]]")
        text = read_profile(tmp_path)
        assert "Personal" in text
        assert "Projects" in text
        assert "姓名: Alice" in text
        assert "[[Project Alpha]]" in text
