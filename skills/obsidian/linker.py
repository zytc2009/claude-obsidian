"""
linker.py — Link suggestions, topic suggestions, and topic-scout clustering.

Reads from the vault and the existing ``_events.jsonl`` feedback
stream to recommend wikilinks for newly-created notes, and clusters
orphan notes (no topic parent) into proposed Topic groupings.

Behavior parity with the original ``obsidian_writer`` implementation
is preserved exactly so ranking, scoring, and clustering output stay
stable for downstream tooling and tests.

Dependencies:
  - :mod:`log_writer` for ``EVENTS_FILE`` and ``normalize_feedback_target``
  - :mod:`frontmatter` for wikilink + frontmatter parsing
  - optional ``session_memory`` for cross-call rejection tracking
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterable

try:
    from . import frontmatter as fm
    from .log_writer import (
        EVENTS_FILE,
        _safe_session_memory,
        normalize_feedback_target,
    )
except ImportError:  # script-mode fallback
    import frontmatter as fm  # type: ignore[no-redef]
    from log_writer import (  # type: ignore[no-redef]
        EVENTS_FILE,
        _safe_session_memory,
        normalize_feedback_target,
    )


# ---------------------------------------------------------------------------
# Stem keywords / topic candidate helpers
# ---------------------------------------------------------------------------


def suggestion_keywords_from_stem(stem: str) -> list[str]:
    """Extract meaningful keywords from a note stem for link suggestion.

    Drops type prefixes (``Literature``, ``Concept``, ...), trailing
    date suffixes, common stop words, and tokens shorter than 4 chars
    (3 chars allowed if all-uppercase, e.g. ``RAG``).
    """

    normalized_stem = re.sub(r"\s\d{4}-\d{2}-\d{2}$", "", stem)
    stop_words = {
        "with", "from", "that", "this", "into", "over", "under",
        "about", "have", "been", "were", "will", "does", "their",
    }
    type_prefixes = ("Literature", "Concept", "Topic", "Project", "MOC")

    keywords: list[str] = []
    for word in re.split(r"[\s\-_]+", normalized_stem):
        if not word:
            continue
        if word.startswith(type_prefixes):
            continue
        if re.fullmatch(r"\d{4}(?:\d{2}){0,2}", word):
            continue
        if len(word) >= 4 or (len(word) == 3 and word.isupper()):
            if word.lower() not in stop_words:
                keywords.append(word)
    return keywords


def topic_candidate_from_stem(stem: str) -> str:
    """Extract a reasonable topic candidate from a note stem."""

    prefix_stop = {"literature", "concept", "topic", "project", "moc"}
    suffix_stop = {
        "survey", "surveys", "notes", "note", "draft", "article", "paper",
        "blog", "overview", "guide", "tutorial", "summary",
    }
    words = [w for w in re.split(r"[\s\-_]+", stem) if w]
    while words and words[0].lower() in prefix_stop:
        words.pop(0)
    while words and words[-1].lower() in suffix_stop:
        words.pop()

    filtered = [w for w in words if len(w) >= 3]
    if not filtered:
        return ""
    return " ".join(filtered[:4])


# ---------------------------------------------------------------------------
# Feedback adjustments / session rejections
# ---------------------------------------------------------------------------


def load_feedback_adjustments(
    vault: Path, suggestion_type: str, source_note: str
) -> dict[str, dict[str, int]]:
    """Return per-target feedback counts for a source note + suggestion type."""

    events_path = vault / EVENTS_FILE
    if not events_path.exists():
        return {}

    adjustments: dict[str, dict[str, int]] = {}
    try:
        with events_path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event.get("event_type") != "suggestion_feedback":
                    continue
                if event.get("suggestion_type") != suggestion_type:
                    continue
                if event.get("source_note") != source_note:
                    continue
                action = event.get("action")
                if action not in {"reject", "modify-accept"}:
                    continue
                for target in event.get("target_notes", []):
                    target_name = normalize_feedback_target(target)
                    if not target_name:
                        continue
                    target_adj = adjustments.setdefault(
                        target_name, {"reject": 0, "modify-accept": 0}
                    )
                    target_adj[action] += 1
    except OSError:
        return {}
    return adjustments


def session_rejected_targets(vault: Path, source_note: str) -> set[str]:
    """Return targets rejected in the current session for a source note."""

    session = _safe_session_memory(vault)
    if session is None:
        return set()
    try:
        rejected = session.to_dict().get("rejected_targets", {}).get(source_note, [])
    except Exception:
        return set()
    return {str(item).strip() for item in rejected if str(item).strip()}


# ---------------------------------------------------------------------------
# Link suggestion
# ---------------------------------------------------------------------------


def suggest_links(vault: Path, new_note_path: Path) -> list[tuple[Path, str]]:
    """Return MOC/Topic notes that likely should link to ``new_note_path``.

    Returns a list of ``(relative_path, section_hint)`` tuples ranked
    by score (descending). Penalties are applied for prior rejections
    (in ``_events.jsonl``) and current-session rejections.
    """

    stem = new_note_path.stem
    words = suggestion_keywords_from_stem(stem)
    if not words:
        return []

    feedback_adjustments = load_feedback_adjustments(vault, "link", stem)
    session_rejections = session_rejected_targets(vault, stem)
    candidates: list[tuple[int, Path, str]] = []
    search_plan = [
        (
            "03-Knowledge/Topics",
            2,
            "# 相关项目" if new_note_path.stem.startswith("Project - ") else "# 重要资料",
        ),
        ("03-Knowledge/MOCs", 1, "# 资料"),
    ]
    max_suggestions = 3

    for search_dir, base_score, section in search_plan:
        target_dir = vault / search_dir
        if not target_dir.exists():
            continue
        for md_file in target_dir.glob("*.md"):
            if md_file == new_note_path:
                continue
            try:
                text = md_file.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if new_note_path.stem in text:
                continue

            title_text = md_file.stem.lower()
            body_text = text.lower()
            title_words = [w for w in words if w.lower() in title_text]
            body_words = [w for w in words if w.lower() in body_text]
            raw_score = base_score + len(title_words) * 2 + len(body_words)
            penalty_meta = feedback_adjustments.get(md_file.stem, {})
            penalty = (
                penalty_meta.get("reject", 0) * 3
                + penalty_meta.get("modify-accept", 0)
            )
            if md_file.stem in session_rejections:
                penalty += 4
            score = raw_score - penalty
            if score <= base_score:
                continue
            strength = "high" if base_score == 2 else "medium"
            reason_parts = [f"strength={strength}"]
            if title_words:
                reason_parts.append(f"title={', '.join(title_words[:3])}")
            if body_words:
                reason_parts.append(f"body={', '.join(body_words[:3])}")
            if penalty_meta.get("reject", 0):
                reason_parts.append(f"feedback=rejectx{penalty_meta['reject']}")
            if penalty_meta.get("modify-accept", 0):
                reason_parts.append(
                    f"feedback=modify-acceptx{penalty_meta['modify-accept']}"
                )
            if md_file.stem in session_rejections:
                reason_parts.append("session=reject")
            reason = "; ".join(reason_parts)
            candidates.append(
                (score, md_file.relative_to(vault), f"{section}; {reason}")
            )

    candidates.sort(key=lambda item: (-item[0], str(item[1])))
    return [(rel, section) for _, rel, section in candidates[:max_suggestions]]


def suggest_new_topic(new_note_path: Path, suggestions: list) -> str:
    """Suggest a new topic name when no existing topic is a strong fit."""

    if "Topics" in new_note_path.parts or new_note_path.stem.startswith("Topic - "):
        return ""
    has_topic_match = any("Topics" in Path(rel).parts for rel, _ in suggestions)
    if has_topic_match:
        return ""

    phrase = topic_candidate_from_stem(new_note_path.stem)
    if not phrase:
        return ""
    return f"Consider creating: Topic - {phrase}"


# ---------------------------------------------------------------------------
# Topic scout
# ---------------------------------------------------------------------------

SCOUT_STOP_WORDS = {
    # English
    "the", "and", "for", "with", "from", "that", "this", "into", "over",
    "under", "about", "have", "been", "were", "will", "does", "their",
    "using", "based", "more", "less", "also", "when", "where", "what",
    "how", "why", "can", "its", "are", "not", "but", "has", "had",
    # Type prefixes (not useful for clustering)
    "literature", "concept", "topic", "project", "moc",
    # Generic note words
    "notes", "note", "draft", "article", "paper", "blog", "survey",
    "overview", "guide", "tutorial", "summary",
}

SCOUT_SCAN_DIRS = {"00-Inbox", "03-Knowledge"}
SCOUT_SKIP_SUBDIRS = {"Topics"}
SCOUT_MIN_CLUSTER = 2
SCOUT_SIMILARITY_THRESHOLD = 0.10
SCOUT_TOP_WORDS = 4
SCOUT_STEM_THRESHOLD = 0.25

# Chinese section header patterns that are note-template boilerplate.
SCOUT_BOILERPLATE = {
    "资料信息", "与已有知识的连接", "原文主要内容", "核心观点", "方法要点",
    "存疑之处", "我的疑问", "可转化概念", "验证实验", "知识连接", "细节",
    "一句话定义", "解决什么问题", "核心机制", "关键公式或流程", "优点",
    "局限", "适用场景", "常见误区", "我的理解", "相关链接",
    "主题说明", "核心问题", "重要资料", "相关项目", "当前结论", "未解决问题",
    "项目描述", "原因分析", "排查过程", "解决方案", "结果验证", "风险与遗留问题",
}


def split_mixed_tokens(text: str) -> list[str]:
    """Split text on whitespace/punctuation and at CJK↔ASCII boundaries."""

    parts = re.split(r"[\s\-_：:与、，。！？（）()【】\[\]《》<>「」\|/\\]+", text)
    result: list[str] = []
    for part in parts:
        if not part:
            continue
        sub = re.sub(r"([A-Za-z0-9])(?=[一-鿿])", r"\1 ", part)
        sub = re.sub(r"([一-鿿])(?=[A-Za-z0-9])", r"\1 ", sub)
        result.extend(sub.split())
    return result


def normalize_token(t: str) -> str | None:
    """Normalize a raw token; return None if it should be discarded."""

    t = t.lower().strip()
    if len(t) < 3:
        return None
    if t in SCOUT_STOP_WORDS or t in SCOUT_BOILERPLATE:
        return None
    if re.fullmatch(r"[\d\-:]+", t):
        return None
    return t


def scout_keywords(stem: str, fmd: dict, body: str) -> dict[str, int]:
    """Weighted keyword counter for clustering.

    Stem and tag tokens get weight 3, body tokens get weight 1.
    """

    counter: dict[str, int] = {}

    def add(tokens: Iterable[str], weight: int) -> None:
        for raw in tokens:
            t = normalize_token(raw)
            if t:
                counter[t] = max(counter.get(t, 0), weight)

    add(split_mixed_tokens(stem), weight=3)

    tags = fmd.get("tags", [])
    if isinstance(tags, str):
        tags = [tags]
    for tag in tags:
        add(split_mixed_tokens(str(tag)), weight=3)

    clean_body = re.sub(r"^#+\s.*$", "", body, flags=re.MULTILINE)
    clean_body = clean_body.replace("_待补充_", "")
    add(split_mixed_tokens(clean_body[:500]), weight=1)

    return counter


def jaccard(a: dict[str, int], b: dict[str, int]) -> float:
    """Weighted Jaccard similarity between two keyword counters."""

    if not a or not b:
        return 0.0
    keys = set(a) | set(b)
    numerator = sum(min(a.get(k, 0), b.get(k, 0)) for k in keys)
    denominator = sum(max(a.get(k, 0), b.get(k, 0)) for k in keys)
    return numerator / denominator if denominator else 0.0


def stem_jaccard(
    a: dict[str, int], b: dict[str, int], min_weight: int = 3
) -> float:
    """Jaccard similarity using only high-weight (stem/tag) keywords."""

    a_high = {k for k, v in a.items() if v >= min_weight}
    b_high = {k for k, v in b.items() if v >= min_weight}
    if not a_high or not b_high:
        return 0.0
    return len(a_high & b_high) / len(a_high | b_high)


def cluster_notes(
    notes: list[tuple[Path, dict[str, int]]],
    threshold: float = SCOUT_SIMILARITY_THRESHOLD,
) -> list[list[tuple[Path, dict[str, int]]]]:
    """Greedy single-linkage clustering by Jaccard keyword overlap."""

    clusters: list[list[tuple[Path, dict[str, int]]]] = []
    assigned: set[int] = set()

    for i, (path_i, kw_i) in enumerate(notes):
        if i in assigned:
            continue
        cluster = [(path_i, kw_i)]
        assigned.add(i)
        changed = True
        while changed:
            changed = False
            for j, (path_j, kw_j) in enumerate(notes):
                if j in assigned:
                    continue
                if any(
                    jaccard(kw_j, kw_m) >= threshold
                    or stem_jaccard(kw_j, kw_m) >= SCOUT_STEM_THRESHOLD
                    for _, kw_m in cluster
                ):
                    cluster.append((path_j, kw_j))
                    assigned.add(j)
                    changed = True
        clusters.append(cluster)

    return clusters


def suggest_cluster_name(cluster: list[tuple[Path, dict[str, int]]]) -> str:
    """Pick a topic name from keywords shared across the most cluster notes."""

    note_count: dict[str, int] = {}
    max_weight: dict[str, int] = {}
    for _, counter in cluster:
        for kw, w in counter.items():
            note_count[kw] = note_count.get(kw, 0) + 1
            max_weight[kw] = max(max_weight.get(kw, 0), w)

    strong = {w for w, c in note_count.items() if c >= 2 and max_weight[w] >= 3}
    if not strong:
        strong = {w for w, c in note_count.items() if c >= 2}
    if not strong:
        strong = set(max_weight)

    ranked = sorted(strong, key=lambda w: (-note_count[w], -max_weight[w]))
    ascii_only = [w for w in ranked if re.fullmatch(r"[a-z0-9]+", w)]
    top = (ascii_only or ranked)[:SCOUT_TOP_WORDS]
    return " ".join(w.capitalize() for w in top) if top else "Unknown"


def scout_topics(
    vault: Path,
    min_cluster_size: int = SCOUT_MIN_CLUSTER,
    threshold: float = SCOUT_SIMILARITY_THRESHOLD,
) -> None:
    """Find orphan notes and cluster them into proposed topic groups (prints to stdout)."""

    topic_dir = vault / "03-Knowledge" / "Topics"
    parented: set[str] = set()
    if topic_dir.exists():
        for topic_file in topic_dir.glob("*.md"):
            text = topic_file.read_text(encoding="utf-8", errors="replace")
            for link in fm.extract_wikilinks(text):
                parented.add(link)

    candidates: list[tuple[Path, dict[str, int]]] = []
    for scan_dir_name in SCOUT_SCAN_DIRS:
        scan_dir = vault / scan_dir_name
        if not scan_dir.exists():
            continue
        for note_file in scan_dir.rglob("*.md"):
            rel_parts = note_file.relative_to(vault).parts
            if any(p in SCOUT_SKIP_SUBDIRS for p in rel_parts):
                continue
            if note_file.stem in parented:
                continue
            try:
                text = note_file.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            fmd = fm.parse_dict(text)
            body = re.sub(r"^---.*?---\s*", "", text, count=1, flags=re.DOTALL)
            keywords = scout_keywords(note_file.stem, fmd, body)
            candidates.append((note_file, keywords))

    if not candidates:
        print("✓ No orphan notes found — all notes have a topic parent.")
        return

    all_clusters = cluster_notes(candidates, threshold=threshold)
    clusters = [c for c in all_clusters if len(c) >= min_cluster_size]
    singletons = [c[0] for c in all_clusters if len(c) < min_cluster_size]

    print(f"[Topic Scout] Scanned {len(candidates)} orphan note(s)\n")

    if clusters:
        print(f"Found {len(clusters)} cluster(s) — consider creating a topic for each:\n")
        for idx, cluster in enumerate(clusters, 1):
            name = suggest_cluster_name(cluster)
            print(f"Cluster {idx} ({len(cluster)} notes) → suggested: Topic - {name}")
            for note_path, _ in cluster:
                rel = note_path.relative_to(vault)
                print(f"  [[{note_path.stem}]]  ({rel})")
            print()

    if singletons:
        print(f"Singletons ({len(singletons)} note(s) with no close match):")
        for note_path, _ in singletons:
            rel = note_path.relative_to(vault)
            print(f"  [[{note_path.stem}]]  ({rel})")
        print()

    if not clusters and not singletons:
        print("✓ No orphan notes found.")
