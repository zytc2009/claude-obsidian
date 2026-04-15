import json
import tempfile
from pathlib import Path
import pytest
from skills.obsidian.memory_manager import MemoryManager, _MEMORY_FILE

@pytest.fixture
def vault(tmp_path):
    return tmp_path

class TestMemoryManagerLoad:
    def test_loads_empty_when_no_file(self, vault):
        mm = MemoryManager(vault)
        assert mm._long_term == {}

    def test_loads_existing_entries(self, vault):
        entry = {
            "word": "Titans", "aliases": ["test-time"],
            "activation_score": 0.8, "frequency": 5,
            "last_activated": "2026-04-15T10:00:00",
            "created": "2026-04-10T09:00:00",
            "decay_rate": 0.05, "obsidian_links": []
        }
        (vault / _MEMORY_FILE).write_text(
            json.dumps(entry, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        mm = MemoryManager(vault)
        assert "Titans" in mm._long_term
        assert mm._long_term["Titans"]["frequency"] == 5

class TestUpsert:
    def test_creates_new_entry(self, vault):
        mm = MemoryManager(vault)
        mm.upsert("CMS", aliases=["连续记忆系统"])
        assert "CMS" in mm._long_term
        assert mm._long_term["CMS"]["frequency"] == 1
        assert "连续记忆系统" in mm._long_term["CMS"]["aliases"]

    def test_increments_frequency_on_duplicate(self, vault):
        mm = MemoryManager(vault)
        mm.upsert("CMS")
        mm.upsert("CMS")
        assert mm._long_term["CMS"]["frequency"] == 2

    def test_merges_aliases_without_duplicates(self, vault):
        mm = MemoryManager(vault)
        mm.upsert("CMS", aliases=["连续记忆"])
        mm.upsert("CMS", aliases=["连续记忆", "多频率层"])
        aliases = mm._long_term["CMS"]["aliases"]
        assert aliases.count("连续记忆") == 1
        assert "多频率层" in aliases

    def test_adds_obsidian_link(self, vault):
        mm = MemoryManager(vault)
        mm.upsert("CMS", obsidian_link="Literature - CMS论文.md")
        assert "Literature - CMS论文.md" in mm._long_term["CMS"]["obsidian_links"]

    def test_does_not_duplicate_obsidian_link(self, vault):
        mm = MemoryManager(vault)
        mm.upsert("CMS", obsidian_link="Literature - CMS论文.md")
        mm.upsert("CMS", obsidian_link="Literature - CMS论文.md")
        assert mm._long_term["CMS"]["obsidian_links"].count("Literature - CMS论文.md") == 1

class TestSave:
    def test_save_and_reload(self, vault):
        mm = MemoryManager(vault)
        mm.upsert("RAG", aliases=["检索增强"])
        mm._save()
        mm2 = MemoryManager(vault)
        assert "RAG" in mm2._long_term
        assert "检索增强" in mm2._long_term["RAG"]["aliases"]
