"""
memory_manager.py — 活性记忆系统

两层记忆：
  长期层：_memory.jsonl，跨会话，真实时间衰减
  短期层：内存 dict，当前会话，巩固时晋升到长期层
"""

import json
import math
import re
from datetime import datetime
from pathlib import Path

_MEMORY_FILE = "_memory.jsonl"
_MAX_MEMORY_ITEMS = 500
_MIN_ACTIVATION_THRESHOLD = 0.1
_INITIAL_ACTIVATION_SCORE = 0.6
_INITIAL_DECAY_RATE = 0.1

_STOPWORDS = set(
    "的 是 了 在 和 与 或 但 因 为 所 以 如 果 那 么 这 个 一 个 "
    "a an the and or but in on at to of for with by is are was were".split()
)


def _extract_keywords(text: str) -> list:
    """从文本中提取关键词（名词、专有词，无 ML 依赖）。"""
    if not text:
        return []
    wikilinks = [m.split('|')[0].strip() for m in re.findall(r'\[\[([^\]]+)\]\]', text)]
    tags = re.findall(r'#(\w+)', text)
    english = re.findall(r'\b[A-Z][a-zA-Z]{1,}\b', text)
    chinese = re.findall(r'[\u4e00-\u9fff]{2,4}', text)
    all_words = wikilinks + tags + english + chinese

    def _is_meaningful(word: str) -> bool:
        if word.lower() in _STOPWORDS:
            return False
        if len(word) < 2:
            return False
        # 过滤完全由停用词组成的中文词
        if all(ch in _STOPWORDS for ch in word):
            return False
        return True

    return [w for w in all_words if _is_meaningful(w)]


class MemoryManager:
    def __init__(self, vault: Path):
        self.vault = vault
        self._memory_path = vault / _MEMORY_FILE
        self._long_term: dict = {}   # word -> entry dict
        self._short_term: dict = {}  # word -> activation count this session
        self._load()

    def _load(self):
        if not self._memory_path.exists():
            return
        with self._memory_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                self._long_term[entry["word"]] = entry

    def _save(self):
        self._memory_path.parent.mkdir(parents=True, exist_ok=True)
        with self._memory_path.open("w", encoding="utf-8") as f:
            for entry in self._long_term.values():
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def _current_activation(self, entry: dict) -> float:
        last = datetime.fromisoformat(entry["last_activated"])
        days = (datetime.now() - last).total_seconds() / 86400
        base = entry["activation_score"] * math.exp(-entry["decay_rate"] * days)
        freq_bonus = math.log(entry["frequency"] + 1) * 0.1
        return min(1.0, base + freq_bonus)

    def upsert(self, word: str, aliases: list = None, obsidian_link: str = None):
        """新增或更新长期记忆中的词条。"""
        if word in self._long_term:
            entry = dict(self._long_term[word])
            entry["frequency"] += 1
            entry["last_activated"] = datetime.now().isoformat(timespec="seconds")
            if aliases:
                existing = set(entry.get("aliases", []))
                entry["aliases"] = list(existing | set(aliases))
            if obsidian_link:
                links = list(entry.get("obsidian_links", []))
                if obsidian_link not in links:
                    links.append(obsidian_link)
                entry["obsidian_links"] = links
        else:
            now = datetime.now().isoformat(timespec="seconds")
            entry = {
                "word": word,
                "aliases": list(aliases) if aliases else [],
                "activation_score": _INITIAL_ACTIVATION_SCORE,
                "frequency": 1,
                "last_activated": now,
                "created": now,
                "decay_rate": _INITIAL_DECAY_RATE,
                "obsidian_links": [obsidian_link] if obsidian_link else [],
            }
        self._long_term[word] = entry

    def run_decay(self):
        """更新所有词条的激活分数，淘汰低于阈值的词条。"""
        updated = {}
        for word, entry in self._long_term.items():
            score = self._current_activation(entry)
            if score >= _MIN_ACTIVATION_THRESHOLD:
                entry = dict(entry)
                entry["activation_score"] = round(score, 4)
                updated[word] = entry
        self._long_term = updated

    def prune(self, max_items: int = _MAX_MEMORY_ITEMS):
        """保留激活分数最高的 max_items 条词条。"""
        if len(self._long_term) <= max_items:
            return
        sorted_entries = sorted(
            self._long_term.values(),
            key=lambda e: self._current_activation(e),
            reverse=True,
        )
        self._long_term = {e["word"]: e for e in sorted_entries[:max_items]}

    def query(self, keywords: list) -> list:
        """返回最多 5 条最相关的活性词，按激活分数排序。"""
        matched = set()
        for kw in keywords:
            kw_lower = kw.lower()
            for word, entry in self._long_term.items():
                if kw_lower in word.lower():
                    matched.add(word)
                    continue
                for alias in entry.get("aliases", []):
                    if kw_lower in alias.lower():
                        matched.add(word)
                        break

        # 同 obsidian_link 的关联词
        matched_links = set()
        for word in matched:
            links = set(self._long_term[word].get("obsidian_links", []))
            for other_word, other_entry in self._long_term.items():
                if other_word not in matched:
                    other_links = set(other_entry.get("obsidian_links", []))
                    if links & other_links:
                        matched_links.add(other_word)

        all_matched = matched | matched_links
        results = [self._long_term[w] for w in all_matched]
        results.sort(key=lambda e: self._current_activation(e), reverse=True)
        return results[:5]

    def activate(self, word: str):
        """强化长期记忆中的词，并记录短期激活次数。"""
        self._short_term[word] = self._short_term.get(word, 0) + 1
        if word in self._long_term:
            entry = dict(self._long_term[word])
            entry["activation_score"] = min(1.0, round(entry["activation_score"] + 0.3, 4))
            entry["decay_rate"] = round(entry["decay_rate"] * 0.9, 4)
            entry["frequency"] += 1
            entry["last_activated"] = datetime.now().isoformat(timespec="seconds")
            self._long_term[word] = entry

    def consolidate_and_flush(self):
        """将短期激活词晋升到长期库，运行衰减，保存到磁盘。
        由 Claude Code Stop hook 触发。"""
        for word, count in self._short_term.items():
            if count >= 2 and word not in self._long_term:
                self.upsert(word)
        self.run_decay()
        self.prune()
        self._save()
        self._short_term.clear()

    def format_context(self) -> str:
        """格式化 top-5 活性词，用于注入 Agent 上下文。"""
        top = sorted(
            self._long_term.values(),
            key=lambda e: self._current_activation(e),
            reverse=True,
        )[:5]
        if not top:
            return ""
        lines = ["<active_memory>"]
        for entry in top:
            score = self._current_activation(entry)
            aliases_str = ", ".join(entry.get("aliases", []))
            line = f"● {entry['word']} ({score:.2f})"
            if aliases_str:
                line += f"  别名: {aliases_str}"
            links = entry.get("obsidian_links", [])
            if links:
                line += f"\n  → [[{links[0]}]]"
            lines.append(line)
        lines.append("</active_memory>")
        return "\n".join(lines)

    def show_status(self, top_n: int = 20) -> str:
        """返回人类可读的活性词库状态。"""
        entries = sorted(
            self._long_term.values(),
            key=lambda e: self._current_activation(e),
            reverse=True,
        )[:top_n]
        if not entries:
            return "[Memory] 活性词库为空"
        lines = [f"[Memory] 活性词库 top-{min(top_n, len(entries))} / {len(self._long_term)} 条\n"]
        for i, entry in enumerate(entries, 1):
            score = self._current_activation(entry)
            lines.append(
                f"  {i:2}. {entry['word']:<20} score={score:.2f}  freq={entry['frequency']}"
            )
        return "\n".join(lines)

    def extract_and_upsert(self, note_type: str, title: str, fields: dict, note_filename: str):
        """从笔记字段提取关键词并写入记忆库。写笔记后自动调用。"""
        if note_type == "concept":
            aliases = _extract_keywords(fields.get("一句话定义", ""))
            self.upsert(title, aliases=aliases, obsidian_link=note_filename)
        elif note_type == "literature":
            for kw in _extract_keywords(fields.get("核心观点", "")):
                self.upsert(kw, obsidian_link=note_filename)
        elif note_type == "topic":
            for kw in _extract_keywords(fields.get("当前结论", "")):
                self.upsert(kw, obsidian_link=note_filename)
        # moc / project / fleeting 暂不提取


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------

def main(argv=None):
    import argparse
    import os
    import sys

    parser = argparse.ArgumentParser(description="活性记忆系统 CLI")
    parser.add_argument("--vault", default=os.environ.get("OBSIDIAN_VAULT_PATH", "~/obsidian"))
    parser.add_argument("--mode", required=True,
        choices=["query", "activate", "reinforce", "forget", "status", "flush", "decay"])
    parser.add_argument("--keywords", default="", help="逗号分隔的关键词（query 模式）")
    parser.add_argument("--word", default="", help="目标词（activate/reinforce/forget 模式）")
    args = parser.parse_args(argv)

    vault = Path(args.vault).expanduser()
    mm = MemoryManager(vault)

    if args.mode == "query":
        keywords = [k.strip() for k in args.keywords.split(",") if k.strip()]
        ctx = mm.format_context() if not keywords else ""
        if keywords:
            results = mm.query(keywords)
            for r in results:
                mm.activate(r["word"])
            ctx = mm.format_context()
        print(ctx or "[Memory] 无相关活性记忆")

    elif args.mode in ("activate", "reinforce"):
        if not args.word:
            print("[Error] --word 必填", file=sys.stderr)
            sys.exit(1)
        mm.activate(args.word)
        mm._save()
        print(f"[Memory] 已强化: {args.word}")

    elif args.mode == "forget":
        if not args.word:
            print("[Error] --word 必填", file=sys.stderr)
            sys.exit(1)
        if args.word in mm._long_term:
            del mm._long_term[args.word]
            mm._save()
            print(f"[Memory] 已淡忘: {args.word}")
        else:
            print(f"[Memory] 未找到: {args.word}")

    elif args.mode == "status":
        print(mm.show_status())

    elif args.mode == "flush":
        mm.consolidate_and_flush()
        print("[Memory] 会话巩固完成，已保存")

    elif args.mode == "decay":
        before = len(mm._long_term)
        mm.run_decay()
        mm.prune()
        mm._save()
        after = len(mm._long_term)
        print(f"[Memory] 衰减完成：{before} → {after} 条")


if __name__ == "__main__":
    main()
