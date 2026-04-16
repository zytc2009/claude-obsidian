import json
from datetime import datetime, timedelta
from pathlib import Path
import pytest
from skills.obsidian.memory_manager import MemoryManager, _MEMORY_FILE, main

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

    def test_merges_topic_links_without_duplicates(self, vault):
        mm = MemoryManager(vault)
        mm.upsert("CMS", topic_links=["Topic - Memory"])
        mm.upsert("CMS", topic_links=["Topic - Memory", "Topic - Titans"])
        assert sorted(mm._long_term["CMS"]["topic_links"]) == [
            "Topic - Memory",
            "Topic - Titans",
        ]

class TestSave:
    def test_save_and_reload(self, vault):
        mm = MemoryManager(vault)
        mm.upsert("RAG", aliases=["检索增强"])
        mm._save()
        mm2 = MemoryManager(vault)
        assert "RAG" in mm2._long_term
        assert "检索增强" in mm2._long_term["RAG"]["aliases"]


class TestUpsertImmutability:
    def test_upsert_does_not_mutate_previous_entry(self, vault):
        mm = MemoryManager(vault)
        mm.upsert("CMS", obsidian_link="file1.md")
        original_links = mm._long_term["CMS"]["obsidian_links"]
        original_id = id(original_links)
        mm.upsert("CMS", obsidian_link="file2.md")
        # The new entry should have a fresh list, not the same object
        assert id(mm._long_term["CMS"]["obsidian_links"]) != original_id or \
               len(original_links) == 1  # original list was not mutated

    def test_upsert_updates_last_activated_on_existing(self, vault):
        import time
        mm = MemoryManager(vault)
        mm.upsert("CMS")
        first_ts = mm._long_term["CMS"]["last_activated"]
        time.sleep(0.01)
        mm.upsert("CMS")
        second_ts = mm._long_term["CMS"]["last_activated"]
        assert second_ts >= first_ts


class TestLoadRobustness:
    def test_load_skips_corrupt_lines(self, vault):
        (vault / _MEMORY_FILE).write_text(
            'not-valid-json\n'
            + json.dumps({"word": "Good", "aliases": [], "activation_score": 0.5,
                          "frequency": 1, "last_activated": "2026-04-15T10:00:00",
                          "created": "2026-04-15T10:00:00", "decay_rate": 0.1,
                          "obsidian_links": []}, ensure_ascii=False) + "\n",
            encoding="utf-8"
        )
        mm = MemoryManager(vault)
        assert "Good" in mm._long_term
        assert len(mm._long_term) == 1

    def test_loads_legacy_entry_without_topic_links(self, vault):
        (vault / _MEMORY_FILE).write_text(
            json.dumps(
                {
                    "word": "Legacy",
                    "aliases": [],
                    "activation_score": 0.5,
                    "frequency": 1,
                    "last_activated": "2026-04-15T10:00:00",
                    "created": "2026-04-15T10:00:00",
                    "decay_rate": 0.1,
                    "obsidian_links": [],
                },
                ensure_ascii=False,
            ) + "\n",
            encoding="utf-8",
        )
        mm = MemoryManager(vault)
        assert mm._long_term["Legacy"].get("topic_links", []) == []


class TestDecay:
    def _make_entry(self, vault, word, score, decay_rate, days_ago):
        mm = MemoryManager(vault)
        last = (datetime.now() - timedelta(days=days_ago)).isoformat(timespec="seconds")
        mm._long_term[word] = {
            "word": word, "aliases": [], "activation_score": score,
            "frequency": 1, "last_activated": last, "created": last,
            "decay_rate": decay_rate, "obsidian_links": [],
        }
        return mm

    def test_high_score_word_survives_7_days(self, vault):
        mm = self._make_entry(vault, "Titans", 1.0, 0.05, 7)
        mm.run_decay()
        assert "Titans" in mm._long_term
        assert mm._long_term["Titans"]["activation_score"] > 0.1

    def test_low_freq_word_pruned_after_30_days(self, vault):
        mm = self._make_entry(vault, "OldWord", 1.0, 0.15, 30)
        mm.run_decay()
        assert "OldWord" not in mm._long_term

    def test_decay_resets_time_baseline_after_run(self, vault):
        mm = self._make_entry(vault, "Titans", 1.0, 0.1, 10)
        mm.run_decay()
        first_score = mm._long_term["Titans"]["activation_score"]
        first_last_activated = mm._long_term["Titans"]["last_activated"]

        mm.run_decay()

        second_score = mm._long_term["Titans"]["activation_score"]
        second_last_activated = mm._long_term["Titans"]["last_activated"]
        assert abs(second_score - first_score) < 0.01
        assert second_last_activated >= first_last_activated

    def test_prune_keeps_top_n_by_score(self, vault):
        mm = MemoryManager(vault)
        now = datetime.now().isoformat(timespec="seconds")
        for i in range(10):
            mm._long_term[f"word{i}"] = {
                "word": f"word{i}", "aliases": [],
                "activation_score": i * 0.1, "frequency": 1,
                "last_activated": now, "created": now,
                "decay_rate": 0.01, "obsidian_links": [],
            }
        mm.prune(max_items=5)
        assert len(mm._long_term) == 5
        assert "word9" in mm._long_term
        assert "word0" not in mm._long_term


class TestQuery:
    def _populated_mm(self, vault):
        mm = MemoryManager(vault)
        now = datetime.now().isoformat(timespec="seconds")
        for word, aliases, score, links in [
            ("Titans", ["自参考学习", "test-time"], 0.9, ["Literature - Titans.md"]),
            ("CMS",    ["多频率层", "连续记忆"],    0.7, []),
            ("RAG",    ["检索增强生成"],             0.5, []),
        ]:
            mm._long_term[word] = {
                "word": word, "aliases": aliases,
                "activation_score": score, "frequency": 3,
                "last_activated": now, "created": now,
                "decay_rate": 0.02, "obsidian_links": links,
            }
        return mm

    def test_exact_word_match(self, vault):
        mm = self._populated_mm(vault)
        results = mm.query(["Titans"])
        assert results[0]["word"] == "Titans"

    def test_alias_match(self, vault):
        mm = self._populated_mm(vault)
        results = mm.query(["自参考"])
        words = [r["word"] for r in results]
        assert "Titans" in words

    def test_returns_at_most_5(self, vault):
        mm = MemoryManager(vault)
        now = datetime.now().isoformat(timespec="seconds")
        for i in range(10):
            mm._long_term[f"word{i}"] = {
                "word": f"word{i}", "aliases": [f"alias{i}"],
                "activation_score": 0.5, "frequency": 1,
                "last_activated": now, "created": now,
                "decay_rate": 0.05, "obsidian_links": [],
            }
        results = mm.query(["word"])
        assert len(results) <= 5

    def test_returns_empty_for_no_match(self, vault):
        mm = self._populated_mm(vault)
        results = mm.query(["nonexistent_xyz"])
        assert results == []

    def test_sorted_by_activation_score(self, vault):
        mm = self._populated_mm(vault)
        results = mm.query(["记忆", "Titans", "CMS"])
        scores = [mm._current_activation(r) for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_related_entries_can_match_via_shared_topic_links(self, vault):
        mm = MemoryManager(vault)
        now = datetime.now().isoformat(timespec="seconds")
        mm._long_term["Attention"] = {
            "word": "Attention", "aliases": [],
            "activation_score": 0.9, "frequency": 3,
            "last_activated": now, "created": now,
            "decay_rate": 0.02, "obsidian_links": ["Literature - Attention Survey.md"],
            "topic_links": ["Topic - Attention Mechanism"],
        }
        mm._long_term["FlashAttention"] = {
            "word": "FlashAttention", "aliases": [],
            "activation_score": 0.6, "frequency": 2,
            "last_activated": now, "created": now,
            "decay_rate": 0.02, "obsidian_links": ["Literature - FlashAttention Survey.md"],
            "topic_links": ["Topic - Attention Mechanism"],
        }
        results = mm.query(["Attention"])
        words = [r["word"] for r in results]
        assert "Attention" in words
        assert "FlashAttention" in words


class TestActivate:
    def test_boosts_activation_score(self, vault):
        mm = MemoryManager(vault)
        now = datetime.now().isoformat(timespec="seconds")
        mm._long_term["Titans"] = {
            "word": "Titans", "aliases": [], "activation_score": 0.5,
            "frequency": 2, "last_activated": now, "created": now,
            "decay_rate": 0.1, "obsidian_links": [],
        }
        mm.activate("Titans")
        assert mm._long_term["Titans"]["activation_score"] > 0.5

    def test_activation_capped_at_1(self, vault):
        mm = MemoryManager(vault)
        now = datetime.now().isoformat(timespec="seconds")
        mm._long_term["X"] = {
            "word": "X", "aliases": [], "activation_score": 0.95,
            "frequency": 1, "last_activated": now, "created": now,
            "decay_rate": 0.1, "obsidian_links": [],
        }
        mm.activate("X")
        assert mm._long_term["X"]["activation_score"] <= 1.0

    def test_reduces_decay_rate(self, vault):
        mm = MemoryManager(vault)
        now = datetime.now().isoformat(timespec="seconds")
        mm._long_term["Y"] = {
            "word": "Y", "aliases": [], "activation_score": 0.5,
            "frequency": 1, "last_activated": now, "created": now,
            "decay_rate": 0.1, "obsidian_links": [],
        }
        mm.activate("Y")
        assert mm._long_term["Y"]["decay_rate"] < 0.1

    def test_increments_short_term_counter(self, vault):
        mm = MemoryManager(vault)
        mm.activate("NewWord")
        assert mm._short_term.get("NewWord", 0) == 1
        mm.activate("NewWord")
        assert mm._short_term.get("NewWord", 0) == 2


class TestConsolidate:
    def test_promotes_word_activated_twice(self, vault):
        mm = MemoryManager(vault)
        mm._short_term["NewConcept"] = 2
        mm.consolidate_and_flush()
        assert "NewConcept" in mm._long_term

    def test_discards_word_activated_once(self, vault):
        mm = MemoryManager(vault)
        mm._short_term["Noise"] = 1
        mm.consolidate_and_flush()
        assert "Noise" not in mm._long_term

    def test_clears_short_term_after_flush(self, vault):
        mm = MemoryManager(vault)
        mm._short_term["X"] = 3
        mm.consolidate_and_flush()
        assert mm._short_term == {}

    def test_saves_to_disk_on_flush(self, vault):
        mm = MemoryManager(vault)
        mm._short_term["Persistent"] = 2
        mm.consolidate_and_flush()
        mm2 = MemoryManager(vault)
        assert "Persistent" in mm2._long_term


class TestCLI:
    def test_query_persists_activated_matches(self, vault):
        mm = MemoryManager(vault)
        mm.upsert("Titans")
        mm._save()

        before = MemoryManager(vault)._long_term["Titans"]["frequency"]
        main(["--vault", str(vault), "--mode", "query", "--keywords", "Titans"])
        after = MemoryManager(vault)._long_term["Titans"]["frequency"]

        assert after == before + 1

    def test_activate_persists_new_word_via_consolidation(self, vault):
        main(["--vault", str(vault), "--mode", "activate", "--word", "FreshWord"])
        mm = MemoryManager(vault)
        assert "FreshWord" in mm._long_term


class TestFormatContext:
    def test_returns_empty_string_when_no_memory(self, vault):
        mm = MemoryManager(vault)
        assert mm.format_context() == ""

    def test_includes_active_memory_tags(self, vault):
        mm = MemoryManager(vault)
        now = datetime.now().isoformat(timespec="seconds")
        mm._long_term["Titans"] = {
            "word": "Titans", "aliases": ["自参考学习"],
            "activation_score": 0.9, "frequency": 5,
            "last_activated": now, "created": now,
            "decay_rate": 0.02, "obsidian_links": ["Literature - Titans.md"],
        }
        ctx = mm.format_context()
        assert "<active_memory>" in ctx
        assert "Titans" in ctx
        assert "自参考学习" in ctx
        assert "</active_memory>" in ctx

    def test_returns_at_most_5_items(self, vault):
        mm = MemoryManager(vault)
        now = datetime.now().isoformat(timespec="seconds")
        for i in range(10):
            mm._long_term[f"word{i}"] = {
                "word": f"word{i}", "aliases": [],
                "activation_score": 0.5, "frequency": 1,
                "last_activated": now, "created": now,
                "decay_rate": 0.05, "obsidian_links": [],
            }
        ctx = mm.format_context()
        assert ctx.count("●") <= 5

    def test_prefers_topic_lines_when_topic_links_exist(self, vault):
        mm = MemoryManager(vault)
        now = datetime.now().isoformat(timespec="seconds")
        mm._long_term["Attention"] = {
            "word": "Attention", "aliases": [],
            "activation_score": 0.9, "frequency": 3,
            "last_activated": now, "created": now,
            "decay_rate": 0.02, "obsidian_links": ["Literature - Attention Survey.md"],
            "topic_links": ["Topic - Attention Mechanism"],
        }
        mm._long_term["FlashAttention"] = {
            "word": "FlashAttention", "aliases": [],
            "activation_score": 0.6, "frequency": 2,
            "last_activated": now, "created": now,
            "decay_rate": 0.02, "obsidian_links": ["Literature - FlashAttention Survey.md"],
            "topic_links": ["Topic - Attention Mechanism"],
        }
        ctx = mm.format_context()
        assert "● Topic - Attention Mechanism (topic" in ctx
        assert "from: Attention, FlashAttention" in ctx


from skills.obsidian.memory_manager import _extract_keywords

class TestExtractKeywords:
    def test_extracts_wikilinks(self):
        kws = _extract_keywords("参考 [[Titans论文]] 和 [[CMS设计]]")
        assert "Titans论文" in kws
        assert "CMS设计" in kws

    def test_extracts_hashtags(self):
        kws = _extract_keywords("这是 #AI #记忆系统 的内容")
        assert "AI" in kws
        assert "记忆系统" in kws

    def test_extracts_capitalized_english(self):
        kws = _extract_keywords("Titans and CMS are key concepts")
        assert "Titans" in kws
        assert "CMS" in kws

    def test_extracts_chinese_phrases(self):
        kws = _extract_keywords("活性记忆和遗忘机制是核心")
        assert "活性记忆" in kws or "遗忘机制" in kws

    def test_filters_stopwords(self):
        kws = _extract_keywords("的是了在和与或")
        assert kws == []

    def test_empty_text_returns_empty(self):
        assert _extract_keywords("") == []


class TestExtractAndUpsert:
    def test_concept_note_uses_title_as_word(self, vault):
        mm = MemoryManager(vault)
        mm.extract_and_upsert("concept", "Transformer", {"一句话定义": "一种注意力机制架构"}, "Concept - Transformer.md")
        assert "Transformer" in mm._long_term

    def test_literature_note_extracts_from_core_ideas(self, vault):
        mm = MemoryManager(vault)
        mm.extract_and_upsert("literature", "Titans论文", {"核心观点": "Self-Referential 模型可以自适应学习率"}, "Literature - Titans论文.md")
        words = list(mm._long_term.keys())
        # 应提取出 Self-Referential 或相关中文词
        assert len(words) > 0

    def test_topic_note_extracts_from_conclusions(self, vault):
        mm = MemoryManager(vault)
        mm.extract_and_upsert("topic", "记忆系统", {"当前结论": "CMS 多频率层优于传统双层记忆"}, "Topic - 记忆系统.md")
        words = list(mm._long_term.keys())
        assert "记忆系统" in words

    def test_extracts_explicit_topic_links_from_fields(self, vault):
        mm = MemoryManager(vault)
        mm.extract_and_upsert(
            "literature",
            "Attention Survey",
            {
                "核心观点": "Attention improves sequence modeling",
                "知识连接": "[[Topic - Attention Mechanism]]\n[[Concept - Transformer]]",
            },
            "Literature - Attention Survey.md",
        )
        entry = next(iter(mm._long_term.values()))
        assert entry["topic_links"] == ["Topic - Attention Mechanism"]

    def test_skips_unsupported_note_types(self, vault):
        mm = MemoryManager(vault)
        mm.extract_and_upsert("moc", "AI MOC", {}, "MOC - AI.md")
        assert mm._long_term == {}
