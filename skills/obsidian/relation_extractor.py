from __future__ import annotations

import json
import logging
import os
import re
import warnings
from pathlib import Path

logger = logging.getLogger(__name__)

_MODEL = "claude-haiku-4-5-20251001"
_MAX_CONTENT_TOKENS = 1500
_RELATED_SECTION = "相关概念"
_NOTE_TYPES_ENABLED = {"literature", "concept", "topic", "project"}


def _estimate_tokens(text: str) -> int:
    chinese = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    english = sum(1 for c in text if c.isascii() and c.isalpha())
    return int(chinese * 1.5 + english * 0.25)


def truncate_content_smart(content: str, max_tokens: int = _MAX_CONTENT_TOKENS) -> str:
    if not content or _estimate_tokens(content) <= max_tokens:
        return content
    paragraphs = content.split("\n\n")
    if len(paragraphs) <= 2:
        return content[: max_tokens * 2]
    first, last = paragraphs[0], paragraphs[-1]
    base_tokens = _estimate_tokens(first) + _estimate_tokens(last)
    budget = max_tokens - base_tokens
    middle = sorted(paragraphs[1:-1], key=lambda p: _estimate_tokens(p), reverse=True)
    selected: list[str] = []
    for paragraph in middle:
        cost = _estimate_tokens(paragraph)
        if budget - cost >= 0:
            selected.append(paragraph)
            budget -= cost
    return "\n\n".join([first] + selected + [last])


def _extract_json(text: str) -> str:
    """Extract JSON from markdown code blocks or embedded text."""
    match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if match:
        candidate = match.group(1).strip()
        try:
            json.loads(candidate)
            return candidate
        except json.JSONDecodeError:
            pass
    for start_char in ("{", "["):
        start = text.find(start_char)
        if start == -1:
            continue
        candidate = text[start:]
        try:
            json.loads(candidate)
            return candidate
        except json.JSONDecodeError:
            depth = 0
            in_string = False
            escape_next = False
            for i, ch in enumerate(candidate):
                if escape_next:
                    escape_next = False
                    continue
                if ch == "\\":
                    escape_next = True
                    continue
                if ch == '"':
                    in_string = not in_string
                    continue
                if in_string:
                    continue
                if ch in ("{", "["):
                    depth += 1
                elif ch in ("}", "]"):
                    depth -= 1
                    if depth == 0:
                        snippet = candidate[: i + 1]
                        try:
                            json.loads(snippet)
                            return snippet
                        except json.JSONDecodeError:
                            break
    return text


def _call_llm(system_prompt: str, user_prompt: str) -> str:
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise EnvironmentError("anthropic not installed") from exc
    client = anthropic.Anthropic()
    msg = client.messages.create(
        model=_MODEL,
        max_tokens=1024,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )
    return msg.content[0].text


def extract_concepts(title: str, content: str) -> list[dict]:
    system_prompt = (
        "你是一个专业的知识图谱构建助手。从笔记中提取 3-10 个核心概念。\n"
        "类型：concept（核心概念）/ topic（主题类别）/ entity（人物/组织/工具）。\n"
        "只返回严格 JSON，不要包含解释文字。"
    )
    user_prompt = (
        f"笔记标题：{title}\n"
        f"笔记内容：\n{truncate_content_smart(content)}\n\n"
        '返回格式：{"concepts": [{"name": "...", "type": "...", "description": "..."}]}'
    )
    try:
        raw = _call_llm(system_prompt, user_prompt)
        data = json.loads(_extract_json(raw))
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            concepts = data.get("concepts", [])
            return concepts if isinstance(concepts, list) else []
        return []
    except Exception as e:
        logger.warning(f"extract_concepts failed: {e}")
        return []


def _normalize(name: str) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff]", "", name).lower().strip()


def match_to_vault(concepts: list[dict], vault: Path) -> list[str]:
    all_notes = list(vault.rglob("*.md"))
    stems = {f.stem for f in all_notes}
    stems_norm = {_normalize(s): s for s in stems}

    links: list[str] = []
    for concept in concepts:
        name = str(concept.get("name", "")).strip()
        if not name:
            continue
        if name in stems:
            links.append(f"[[{name}]]")
            continue
        name_norm = _normalize(name)
        if name_norm and name_norm in stems_norm:
            links.append(f"[[{stems_norm[name_norm]}]]")
            continue
        for stem in stems:
            if len(stem) > 20:
                continue
            if name_norm in _normalize(stem) or _normalize(stem) in name_norm:
                links.append(f"[[{stem}]]")
                break
    seen: set[str] = set()
    result: list[str] = []
    for link in links:
        if link not in seen:
            seen.add(link)
            result.append(link)
    return result


def append_related_concepts(note_path: Path, wikilinks: list[str]) -> None:
    if not wikilinks:
        return
    text = note_path.read_text(encoding="utf-8", errors="replace")
    section_header = f"## {_RELATED_SECTION}"

    existing_links: set[str] = set()
    if section_header in text:
        pat = re.compile(rf"(?ms)^## {re.escape(_RELATED_SECTION)}\n(.*?)(?=^## |\Z)")
        match = pat.search(text)
        if match:
            existing_links = set(re.findall(r"\[\[[^\]]+\]\]", match.group(1)))

    new_links = [lnk for lnk in wikilinks if lnk not in existing_links]
    if not new_links:
        return

    addition = "\n".join(new_links)
    if section_header in text:
        text = re.sub(
            rf"(?ms)(^## {re.escape(_RELATED_SECTION)}\n)(.*?)(?=^## |\Z)",
            lambda match: match.group(1) + match.group(2).rstrip() + "\n" + addition + "\n",
            text,
            count=1,
        )
    else:
        if not text.endswith("\n"):
            text += "\n"
        text += f"\n{section_header}\n{addition}\n"
    note_path.write_text(text, encoding="utf-8")


def extract_and_link(vault: Path, note_path: Path) -> list[str]:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise EnvironmentError("ANTHROPIC_API_KEY not set")
    text = note_path.read_text(encoding="utf-8", errors="replace")
    if text.startswith("---"):
        end = text.find("---", 3)
        if end != -1:
            text = text[end + 3 :].lstrip()

    title = note_path.stem
    concepts = extract_concepts(title, text)
    if not concepts:
        return []

    links = match_to_vault(concepts, vault)
    self_link = f"[[{note_path.stem}]]"
    links = [lnk for lnk in links if lnk != self_link]

    if links:
        append_related_concepts(note_path, links)
    return links
